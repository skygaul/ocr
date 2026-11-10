"""공용 OCR/표 복원 로직 (웹 서비스와 run_ocr.py가 함께 사용)."""
import os
import re
import io
import statistics
import threading

import cv2
import numpy as np

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Border, Side, Font
from paddleocr import PaddleOCR

_ocr = {}
_lock = threading.Lock()


def get_ocr(lang):
    # 한국어 모델은 영어/숫자도 함께 인식한다.
    if lang not in _ocr:
        _ocr[lang] = PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,  # Windows CPU에서 oneDNN 오류 회피
        )
    return _ocr[lang]


def run_ocr(path, lang):
    with _lock:
        res = get_ocr(lang).predict(str(path))
    lines = []
    for r in res:
        for text, score, box in zip(r["rec_texts"], r["rec_scores"], r["rec_polys"]):
            lines.append({
                "text": text,
                "score": round(float(score), 4),
                "box": [[int(x), int(y)] for x, y in box],
            })
    # 위->아래, 좌->우 순서로 정렬 (같은 줄은 y 근사치로 묶음)
    lines.sort(key=lambda l: (min(p[1] for p in l["box"]) // 12, min(p[0] for p in l["box"])))
    return lines




# ---------------------------------------------------------------- 표 복원
NUM_RE = re.compile(r"[\d][\d,.\s]*")
DASH_RE = re.compile(r"[\-–—_.·…~=\s]{3,}")


def _is_num(t):
    return bool(NUM_RE.fullmatch(t.strip()))


def _clean(t):
    return re.sub(r"^[\s.·…]+|[\s.·…]+$", "", t) if not _is_num(t) else t.strip()


def detect_hrules(path):
    """이미지에서 긴 가로선(표의 괘선)을 찾아 [[y, x0, x1], ...] 로 반환."""
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    H, W = img.shape
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, int(W * 0.07)), 1))
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k)
    n, _, stats, _ = cv2.connectedComponentsWithStats(opened)
    segs = sorted([int(y + h / 2), int(x), int(x + w)] for x, y, w, h, _a in stats[1:] if h <= 8)
    out = []
    for y, x0, x1 in segs:
        if out and abs(y - out[-1][0]) <= 6:  # 세로선에 끊긴 같은 높이의 조각은 한 줄로 합침
            out[-1] = [(out[-1][0] + y) // 2, min(out[-1][1], x0), max(out[-1][2], x1)]
        else:
            out.append([y, x0, x1])
    return out


def _empty_table():
    return {"caption": [], "caption_cells": [], "header": [], "spans": [], "rows": [], "notes": [], "ncols": 0, "warnings": []}


def build_table(lines, rules=None):
    """OCR 박스 좌표(+ 가로 괘선)로 캡션/머리글/본문/각주를 나누고 행·열을 추정한다."""
    items = []
    for l in lines:
        dash = bool(DASH_RE.fullmatch(l["text"].strip()))
        t = "—" if dash else _clean(l["text"])
        if not t:
            continue
        xs = [p[0] for p in l["box"]]
        ys = [p[1] for p in l["box"]]
        items.append({"t": t, "dash": dash, "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                      "cy": (min(ys) + max(ys)) / 2, "score": l["score"]})
    if not items:
        return _empty_table()

    # 0) 여러 줄이 한 박스로 합쳐진 숫자(예: 세로로 붙은 '2'와 '8' → '28')를 줄 수만큼 분리
    real = [i for i in items if not i["dash"]]
    h = statistics.median(i["y1"] - i["y0"] for i in real) if real else 16
    warnings, fixed = [], []
    for i in items:
        hh = i["y1"] - i["y0"]
        k = round(hh / (h * 0.85))
        if hh >= h * 1.55 and k >= 2 and i["t"].isdigit() and len(i["t"]) == k:
            warnings.append(f"'{i['t']}' 박스가 {k}줄로 합쳐져 있어 한 글자씩 {k}행으로 분리함 (y≈{int(i['y0'])}) — 원본 확인 권장")
            for j, ch in enumerate(i["t"]):
                y0 = i["y0"] + hh * j / k
                y1 = i["y0"] + hh * (j + 1) / k
                fixed.append({**i, "t": ch, "y0": y0, "y1": y1, "cy": (y0 + y1) / 2})
        else:
            fixed.append(i)
    items = fixed

    # 1) 행 묶기 (중심 y 기준)
    items.sort(key=lambda i: i["cy"])
    rows = []
    for it in items:
        if rows and abs(it["cy"] - statistics.mean(r["cy"] for r in rows[-1])) < h * 0.45:
            rows[-1].append(it)
        else:
            rows.append([it])
    rcy = [statistics.mean(i["cy"] for i in r) for r in rows]

    # 2) 본문 구간: 숫자 셀 2개 이상인 첫 행 ~ 숫자 셀이 있는 마지막 행
    numcnt = [sum(_is_num(i["t"]) for i in r) for r in rows]
    start = next((k for k, c in enumerate(numcnt) if c >= 2), 0)
    end = max((k for k, c in enumerate(numcnt) if c >= 1 and k >= start), default=len(rows) - 1)

    # 3) 괘선으로 캡션 / 머리글 / 본문 경계 찾기
    caption_rows, shortr, long_r = [], [], []
    if rules:
        wmax = max(r[2] - r[1] for r in rules)
        long_r = sorted(r for r in rules if r[2] - r[1] >= 0.85 * wmax)
    start_top = min(i["y0"] for i in rows[start])
    hb = max((r for r in long_r if r[0] < start_top), default=None)
    if hb is not None:
        tops = [r for r in long_r if r[0] < hb[0]]
        top = min(tops) if tops else None
        shortr = [r for r in rules if r not in long_r and (top is None or r[0] > top[0]) and r[0] < hb[0]]
        header_rows = [r for k, r in enumerate(rows) if rcy[k] < hb[0] and (top is None or rcy[k] > top[0])]
        caption_rows = [r for k, r in enumerate(rows) if top is not None and rcy[k] < top[0]]
        body_rows = [r for k, r in enumerate(rows) if rcy[k] > hb[0] and k <= end]
    else:  # 괘선을 못 찾음: 숫자 행 앞은 전부 머리글, 단 바로 앞의 떨어진 단독 줄은 소제목(본문)으로 본다
        header_rows, body_rows = rows[:start], rows[start:end + 1]
        if start >= 2 and len(rows[start - 1]) == 1 and rcy[start] - rcy[start - 1] < 2.5 * h \
                and rcy[start - 1] - rcy[start - 2] > 1.8 * h:
            body_rows = [rows[start - 1]] + body_rows
            header_rows = rows[:start - 1]
    note_rows = rows[end + 1:]
    if not body_rows:
        return _empty_table()

    # 4) 열 경계: 본문 박스 x 구간의 빈 틈
    spans_x = sorted((i["x0"], i["x1"]) for r in body_rows for i in r)
    cols, cur = [], list(spans_x[0])
    gap = max(12, h * 0.6)
    for a, b in spans_x[1:]:
        if a - cur[1] > gap:
            cols.append(tuple(cur))
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    cols.append(tuple(cur))

    def col_of(i):
        c = (i["x0"] + i["x1"]) / 2
        return min(range(len(cols)), key=lambda k: 0 if cols[k][0] <= c <= cols[k][1]
                   else min(abs(c - cols[k][0]), abs(c - cols[k][1])))

    def new_cell():
        return {"text": "", "indent": 0, "num": False, "box": None, "score": None}

    def put(c, i):
        c["text"] = (c["text"] + "\n" + i["t"]) if c["text"] else i["t"]
        b = [i["x0"], i["y0"], i["x1"], i["y1"]]
        c["box"] = b if c["box"] is None else [min(c["box"][0], b[0]), min(c["box"][1], b[1]),
                                               max(c["box"][2], b[2]), max(c["box"][3], b[3])]
        c["score"] = i["score"] if c["score"] is None else min(c["score"], i["score"])
        c["num"] = _is_num(c["text"])

    def to_cells(r):
        cells = [new_cell() for _ in cols]
        for i in sorted(r, key=lambda i: (i["cy"], i["x0"])):
            k = col_of(i)
            if i["dash"] and (k == 0 or cells[k]["text"]):
                continue  # 첫 열의 점선 리더 / 이미 값이 있는 칸의 선은 무시
            put(cells[k], i)
            if k == 0:
                cells[k]["indent"] = max(0, int(i["x0"] - cols[0][0]))
        return cells

    # 5) 머리글: 가로 괘선 아래 '묶음 제목'(예: Maturity)과 열 제목 분리
    header_items = [i for r in header_rows for i in r]
    spanners, leaf = [], []
    for it in header_items:
        cx = (it["x0"] + it["x1"]) / 2
        cand = [r for r in shortr if r[0] > it["cy"] and r[1] - 10 <= cx <= r[2] + 10]
        if cand:
            spanners.append((min(cand), it))
        else:
            leaf.append(it)
    spans = []
    for rule in sorted({tuple(r) for r, _ in spanners}):
        its = sorted((i for r, i in spanners if tuple(r) == rule), key=lambda i: (i["cy"], i["x0"]))
        cs = [k for k, (a, b) in enumerate(cols) if b >= rule[1] and a <= rule[2]]
        if cs:
            spans.append({"text": " ".join(i["t"] for i in its), "c0": min(cs), "c1": max(cs),
                          "box": [min(i["x0"] for i in its), min(i["y0"] for i in its),
                                  max(i["x1"] for i in its), max(i["y1"] for i in its)],
                          "score": min(i["score"] for i in its)})
    header = []
    if header_items:
        cells = [new_cell() for _ in cols]
        for i in sorted(leaf, key=lambda i: (i["cy"], i["x0"])):
            put(cells[col_of(i)], i)
        header = [cells]

    caption = [" ".join(i["t"] for i in sorted(r, key=lambda i: i["x0"])) for r in caption_rows]
    caption_cells = [{"text": " ".join(i["t"] for i in sorted(r, key=lambda i: i["x0"])),
                      "box": [min(i["x0"] for i in r), min(i["y0"] for i in r),
                              max(i["x1"] for i in r), max(i["y1"] for i in r)],
                      "score": min(i["score"] for i in r)} for r in caption_rows]
    notes = ["    ".join(i["t"] for i in sorted(r, key=lambda i: i["x0"]) if not i["dash"]) for r in note_rows]
    return {"caption": caption, "caption_cells": caption_cells, "header": header, "spans": spans, "rows": [to_cells(r) for r in body_rows],
            "notes": [n for n in notes if n], "ncols": len(cols), "warnings": warnings}


def _flat(t):
    t = t.replace("\n", " ")
    # 숫자 칸: '6, 861' → '6861' (숫자로 복사·검색·계산할 수 있게 쉼표·공백 제거)
    return re.sub(r"[,\s]", "", t) if _is_num(t) else t


def table_matrix(tb):
    out = []
    if tb["header"]:
        names = []
        for k, c in enumerate(tb["header"][0]):
            sp = next((s for s in tb["spans"] if s["c0"] <= k <= s["c1"]), None)
            names.append((sp["text"] + " / " if sp else "") + _flat(c["text"]))
        out.append(names)
    out += [[_flat(c["text"]) for c in r] for r in tb["rows"]]
    return out


def table_xlsx(tb):
    wb = Workbook()
    ws = wb.active
    ws.title = "OCR"
    thin = Side(style="thin", color="888888")
    n = max(1, tb["ncols"])
    r = 1
    for cap in tb["caption"]:
        ws.cell(row=r, column=1, value=cap).font = Font(bold=True)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=n)
        ws.cell(row=r, column=1).alignment = Alignment(horizontal="center")
        r += 1
    if tb["spans"]:
        for s in tb["spans"]:
            ws.cell(row=r, column=s["c0"] + 1, value=s["text"]).font = Font(bold=True)
            if s["c1"] > s["c0"]:
                ws.merge_cells(start_row=r, start_column=s["c0"] + 1, end_row=r, end_column=s["c1"] + 1)
            ws.cell(row=r, column=s["c0"] + 1).alignment = Alignment(horizontal="center")
        r += 1
    for hdr, rows in ((True, tb["header"]), (False, tb["rows"])):
        for row in rows:
            for k, c in enumerate(row, start=1):
                val = c["text"] if hdr else _flat(c["text"])
                if not hdr and val.isdigit():
                    val = int(val)
                cell = ws.cell(row=r, column=k, value=val)
                if isinstance(val, int):
                    cell.number_format = "#,##0"
                cell.alignment = Alignment(
                    wrap_text=True, vertical="center",
                    horizontal="center" if hdr else ("right" if c["num"] else "left"),
                    indent=0 if hdr or k > 1 else min(15, c["indent"] // 20))
                cell.border = Border(top=thin if hdr else None, bottom=thin if hdr else None)
                if hdr:
                    cell.font = Font(bold=True)
            r += 1
    for k in range(1, n + 1):
        ws.column_dimensions[get_column_letter(k)].width = 36 if k == 1 else 16
    if tb["notes"]:
        r += 1
        for t in tb["notes"]:
            ws.cell(row=r, column=1, value=t)
            r += 1
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
