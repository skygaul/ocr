"""표 이미지 OCR 파이프라인 (Census Table 1 / FRASER No. 11).

    python run_ocr.py                       # census: OCR 실행 + 표/문서 생성
    python run_ocr.py --table fraser        # FRASER No. 11
    python run_ocr.py --build-only          # 저장된 OCR 결과로 표/문서만 다시 생성 (corrections.json 반영)

입력 : input/census-table.png, input/fraser-table.png
출력 : outputs/ocr/ (census), outputs/ocr-fraser/ (fraser)  — README.md 의 '산출물' 표 참고
"""
import argparse
import csv
import hashlib
import itertools
import json
import platform
import re
import shutil
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
LOW_CONF = 0.90

MONTHS = ["Jan. 31", "Feb. 28", "Mar. 28", "Apr. 25", "May 30", "June 27", "July 25", "Aug. 29",
          "Sept. 26", "Oct. 31", "Nov. 28", "Dec. 26", "Jan. 30", "Feb. 27", "Mar. 27", "Apr. 24",
          "May 29", "June 26", "July 31", "Aug. 28", "Sept. 25", "Oct. 30", "Nov. 27", "Dec. 31"]
FRASER_LABELS = ["1934—" + MONTHS[0]] + MONTHS[1:12] + ["1935—" + MONTHS[12]] + MONTHS[13:]

SPECS = {
    "census": {
        "key": "census",
        "input": ROOT / "input" / "census-table.png",
        "out": ROOT / "outputs" / "ocr",
        # 표 영역만 사용 (아래쪽 웹페이지 캡션 줄 "FRASER No. 11 ..."은 표가 아니므로 제외). 좌표는 원본과 동일.
        "crop": (0, 0, 1103, 520),
        "title": "Census Table 1 — 면적과 인구 (표 이미지 → 문서)",
        "source": {
            "table": "Table 1 — Area (Gross area, land and water, in square miles) and Population: 1910",
            "publisher": "U.S. Census Bureau",
            "document": "1910 Census report (published 1913)",
            "pdf_page": 2, "printed_page": 22,
            "license": "미국 연방정부 발행 퍼블릭 도메인 자료 (과제 안내 기준)",
            "image_note": "과제에서 제공한 200 dpi 표 이미지",
        },
        "cols": [("region", "지역명 (AREA)"),
                 ("gross_area_sq_mi", "Gross area (land and water) in square miles"),
                 ("population_1910", "Population: 1910")],
        "ncols": 3, "nrows": 11,
        "checks": [
            {"type": "col_sum", "name": "미국 전체 = 속령 제외 + 속령", "parent": 0, "children": [1, 2]},
            {"type": "col_sum", "name": "속령 = 8개 지역 합", "parent": 2, "children": list(range(3, 11))},
        ],
        "blank_needs_check": True,
        "footnote_markers": {"1", "2"},
        "sup": {"1": "¹", "2": "²"},
        "indent_rows": set(range(3, 11)),
        "label_seq": None,
        "csv": {"cols": ["region", "gross_area_sq_mi", "population_1910"], "section": False, "footnotes": True},
        "blank_note": "빈 칸 `—`: 원본에 값이 인쇄되어 있지 않음(군인·해군 복무자의 면적). 값을 추정해 채우지 않았습니다.",
        "extra_limits": ["이미지 아래쪽의 웹페이지 캡션(`FRASER No. 11 — ...`)은 표가 아니므로 제외했습니다.",
                         "이 표는 3열·11행 구조를 가정한 합계 검산 규칙을 사용합니다."],
    },
    "fraser": {
        "key": "fraser",
        "input": ROOT / "input" / "fraser-table.png",
        "out": ROOT / "outputs" / "ocr-fraser",
        "crop": None,
        "title": "FRASER No. 11 — 연방준비은행 어음 보유액 (표 이미지 → 문서)",
        "source": {
            "table": "No. 11 — Holdings of bills discounted and bills bought by Federal Reserve Banks, by maturities, 1934–35 [In thousands of dollars]",
            "publisher": "Board of Governors of the Federal Reserve System (FRASER 아카이브)",
            "document": "Annual Report of the Federal Reserve System, 1935 (published 1936)",
            "pdf_page": 98, "printed_page": 91,
            "license": "미국 연방정부 발행 퍼블릭 도메인 자료 (과제 안내 기준)",
            "image_note": "과제에서 제공한 200 dpi 표 이미지",
        },
        "cols": [("date", "Date"), ("total", "Total"),
                 ("within_15_days", "Maturity / Within 15 days"), ("d16_to_30", "Maturity / 16 to 30 days"),
                 ("d31_to_60", "Maturity / 31 to 60 days"), ("d61_to_90", "Maturity / 61 to 90 days"),
                 ("d91_to_6m", "Maturity / 91 days to 6 months"), ("over_6m", "Maturity / Over 6 months")],
        "ncols": 8, "nrows": 50,
        "checks": [{"type": "row_sum", "name": "Total = 만기 구간 합", "parent_col": 1,
                    "child_cols": [2, 3, 4, 5, 6, 7]}],
        "blank_needs_check": False,
        "footnote_markers": set(),
        "sup": {},
        "indent_rows": set(),
        "label_seq": FRASER_LABELS,
        "csv": {"cols": ["date", "total", "within_15_days", "d16_to_30", "d31_to_60", "d61_to_90",
                         "d91_to_6m", "over_6m"], "section": True, "footnotes": False},
        "blank_note": "빈 칸 `—`: 원본에 숫자가 아닌 점선(-----)이 인쇄된 칸. 행 합계가 맞으면 비어 있는 것으로 봅니다(단위: 천 달러).",
        "extra_limits": ["`1934`/`1935` 연도는 각 구역 첫 행과 1월 행에만 인쇄되어 있어, CSV의 `date`는 원본 표기 그대로이며 연도를 따로 채우지 않았습니다.",
                         "숫자 단위는 천 달러(thousands of dollars)이며 값을 곱하거나 바꾸지 않았습니다."],
    },
}

SPEC = None
INPUT = OUT = CORRECTIONS = None


def configure(name):
    global SPEC, INPUT, OUT, CORRECTIONS
    SPEC = SPECS[name]
    INPUT, OUT = SPEC["input"], SPEC["out"]
    CORRECTIONS = OUT / "corrections.json"


configure("census")


# ------------------------------------------------------------------ 유틸
def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def parse_int(s):
    t = re.sub(r"\s", "", s or "")
    return int(t.replace(",", "")) if re.fullmatch(r"\d{1,3}(,\d{3})+|\d+", t) else None


def normalize(s):
    """흔한 OCR 혼동(O→0 등)을 바로잡아 본 값. 확정이 아니라 '후보'일 뿐이다."""
    t = re.sub(r"\s", "", s or "")
    t = t.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "B": "8", "S": "5"}))
    t = t.replace(".", "")
    return parse_int(t)


def is_blank(s):
    return (s or "").strip() in ("", "—")


def fmt(v):
    return "" if v is None else f"{v:,}"


def font(size):
    for f in ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def label_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def label_norm(s):
    """날짜 라벨의 형식만 정리: 'Jan.31' → 'Jan. 31' (글자는 바꾸지 않음)."""
    return re.sub(r"\.(?=\d)", ". ", s) if SPEC["label_seq"] else s


# ------------------------------------------------------------------ 1단계: OCR
def stage_ocr(lang):
    import ocrlib  # paddle 로딩이 느리므로 필요할 때만 import

    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INPUT, OUT / f"input_{INPUT.name}")              # 입력 이미지 사본
    img = Image.open(INPUT).convert("RGB")
    crop = img.crop(SPEC["crop"]) if SPEC["crop"] else img
    crop.save(OUT / "table-crop.png")

    ocr = ocrlib.get_ocr(lang)
    res = ocr.predict(str(OUT / "table-crop.png"))
    r = res[0]
    raw = r.json["res"] if hasattr(r, "json") else dict(r)
    raw = dict(raw)
    raw["input_path"] = (OUT / "table-crop.png").relative_to(ROOT).as_posix()  # 개인 PC 경로가 남지 않게 상대경로로
    dump(OUT / "raw_ocr.json", raw)                                 # 모델 원시 출력

    lines = []
    for t, s, box in zip(raw["rec_texts"], raw["rec_scores"], raw["rec_polys"]):
        lines.append({"text": t, "score": round(float(s), 4),
                      "box": [[int(x), int(y)] for x, y in box]})
    lines.sort(key=lambda l: (min(p[1] for p in l["box"]) // 12, min(p[0] for p in l["box"])))
    dump(OUT / "ocr_lines.json", lines)                             # 텍스트·점수·좌표

    vis = crop.copy()
    d = ImageDraw.Draw(vis)
    f = font(13)
    for k, l in enumerate(lines):
        pts = [tuple(p) for p in l["box"]]
        d.polygon(pts, outline=(37, 99, 235), width=2)
        d.text((pts[0][0], max(0, pts[0][1] - 14)), str(k), fill=(220, 38, 38), font=f)
    vis.save(OUT / "ocr_overlay.png")

    try:  # 실제로 사용된 모델 이름 기록
        p = ocr.paddlex_pipeline
        models = {"detection": p.text_det_model.model_name, "recognition": p.text_rec_model.model_name}
    except Exception:  # noqa: BLE001
        models = {"detection": "PP-OCRv5 det (이름 확인 실패)", "recognition": f"lang={lang}"}
    dump(OUT / "ocr_meta.json", {
        "lang": lang, "models": models,
        "settings": {"enable_mkldnn": False, "use_doc_orientation_classify": False,
                     "use_doc_unwarping": False, "use_textline_orientation": False,
                     "device": "cpu"},
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "line_count": len(lines),
    })
    print(f"OCR 완료: {len(lines)}줄")


# ------------------------------------------------------------------ 2단계: 표 구성 + 검토
def one_digit_diff(a, b):
    sa, sb = str(a), str(b)
    return len(sa) == len(sb) and sum(x != y for x, y in zip(sa, sb)) == 1


def propose(parent, vals, raws):
    """합계가 안 맞을 때 원인 칸 후보. 반환 {자식 index: (후보값, 방법)}, 부모 후보는 key -1.
    힌트일 뿐 값을 확정하지 않는다."""
    vals = list(vals)
    unknown = [i for i, v in enumerate(vals) if v is None and not is_blank(raws[i])]
    hints = {}
    for i in unknown:                                    # 1) 글자 혼동 정규화
        n = normalize(raws[i])
        if n is not None:
            vals[i] = n
            hints[i] = (n, "O→0·불필요한 '.' 제거 등 정규화")
    if sum(v or 0 for v in vals) == parent:
        return hints
    markers = SPEC["footnote_markers"]
    if markers:                                           # 2) 각주 번호(위첨자)가 숫자 앞에 붙은 경우
        cand = [i for i, v in enumerate(vals) if v is not None and v >= 10 and str(v)[0] in markers]
        for k in (1, 2):
            for sub in itertools.combinations(cand, k):
                nv = list(vals)
                for i in sub:
                    nv[i] = int(str(vals[i])[1:])
                if sum(v or 0 for v in nv) == parent:
                    for i in sub:
                        hints[i] = (nv[i], f"맨 앞 '{str(vals[i])[0]}'는 각주 번호(위첨자)로 의심")
                    return hints
    if len(unknown) == 1:                                 # 3) 하나만 못 읽었으면 합계로 역산
        i = unknown[0]
        solved = parent - sum(parse_int(raws[j]) or 0 for j in range(len(vals)) if j != i)
        if solved >= 0:
            hints[i] = (solved, "다른 칸의 합과 총합으로 역산한 값")
            return hints
    diff = parent - sum(v or 0 for v in vals)             # 4) 한 칸의 한 자리만 달라서 합이 안 맞는 경우
    found = {}
    for i, v in enumerate(vals):
        if v is not None and v + diff >= 0 and one_digit_diff(v, v + diff):
            found[i] = (v + diff, f"한 자리만 바꾸면 합이 맞는 값 ({v:,}→{v + diff:,})")
        elif v is None and is_blank(raws[i]) and diff > 0:
            found[i] = (diff, f"빈 칸에 {diff:,}이(가) 있었을 가능성 (누락 후보)")
    if parent - diff >= 0 and one_digit_diff(parent, parent - diff):
        found[-1] = (parent - diff, f"총합 칸이 한 자리 다르게 읽혔을 가능성 ({parent:,}→{parent - diff:,})")
    hints.update(found)
    return hints


def check_instances(byid, nrows):
    """표 구조에서 합계 검산 인스턴스 목록을 만든다."""
    out = []
    cols = SPEC["cols"]
    for ck in SPEC["checks"]:
        if ck["type"] == "col_sum":
            for col in range(1, len(cols)):
                pid = f"R{ck['parent']}C{col}"
                kids = [f"R{i}C{col}" for i in ck["children"]]
                if pid in byid and all(k in byid for k in kids):
                    out.append({"name": ck["name"], "scope": cols[col][0], "parent": pid, "children": kids})
        else:  # row_sum
            for r in range(nrows):
                pid = f"R{r}C{ck['parent_col']}"
                kids = [f"R{r}C{c}" for c in ck["child_cols"] if f"R{r}C{c}" in byid]
                if pid in byid and kids:
                    lab = byid.get(f"R{r}C0", {}).get("raw", "")
                    out.append({"name": ck["name"], "scope": f"행 {r}: {lab}", "parent": pid, "children": kids})
    return out


def stage_build():
    lines = load(OUT / "ocr_lines.json")
    meta = load(OUT / "ocr_meta.json", {})
    if lines is None:
        sys.exit(f"{OUT}/ocr_lines.json 이 없습니다. 먼저 python run_ocr.py --table {SPEC['key']} 를 실행하세요.")
    import ocrlib

    tb = ocrlib.build_table(lines, ocrlib.detect_hrules(OUT / "table-crop.png"))
    structure_ok = tb["ncols"] == SPEC["ncols"] and len(tb["rows"]) == SPEC["nrows"] and len(tb["header"]) == 1
    corr = load(CORRECTIONS, {})
    cols = SPEC["cols"]

    cells = []

    def add_cell(cid, kind, row, col, c, row_label=None):
        cells.append({
            "id": cid, "kind": kind, "row": row, "col": col,
            "row_label": row_label, "col_title": cols[col][0] if col is not None and col < len(cols) else None,
            "raw": c["text"], "score": c["score"], "box": c["box"],
            "reasons": [], "hint": None,
        })
        return cells[-1]

    for k, cc in enumerate(tb.get("caption_cells", [])):
        add_cell(f"C{k}", "caption", k, None, cc)
    for k, sp in enumerate(tb.get("spans", [])):
        add_cell(f"S{k}", "span", k, None, sp)
    for k, c in enumerate(tb["header"][0] if tb["header"] else []):
        add_cell(f"H0C{k}", "header", 0, k, c)
    body = []
    for r, row in enumerate(tb["rows"]):
        has_num = any(ocrlib._is_num(c["text"]) for c in row[1:])
        label = row[0]["text"]
        rc = [add_cell(f"R{r}C0", "label" if has_num else "section", r, 0, row[0], label)]
        if has_num:
            for k, c in enumerate(row[1:], start=1):
                rc.append(add_cell(f"R{r}C{k}", "value", r, k, c, label))
        body.append(rc)

    body_bottom = max((c["box"][3] for rc in body for c in rc if c["box"]), default=0)
    notes = []
    for l in lines:
        ys = [p[1] for p in l["box"]]
        xs = [p[0] for p in l["box"]]
        if min(ys) > body_bottom - 2 and not ocrlib.DASH_RE.fullmatch(l["text"].strip()):
            notes.append({"text": l["text"], "score": l["score"],
                          "box": [min(xs), min(ys), max(xs), max(ys)]})
    notes.sort(key=lambda n: (n["box"][1] // 12, n["box"][0]))
    for k, n in enumerate(notes):
        add_cell(f"N{k}", "note", k, None, n)

    byid = {c["id"]: c for c in cells}

    # 자동 의심 규칙 1: 신뢰도, 숫자 형식, 빈 칸
    for c in cells:
        if c["score"] is not None and c["score"] < LOW_CONF:
            c["reasons"].append(f"OCR 신뢰도 낮음 ({c['score']:.2f})")
        if c["kind"] == "value":
            if is_blank(c["raw"]):
                if SPEC["blank_needs_check"]:
                    c["reasons"].append("빈 칸 (원본에 값이 있는지 확인)")
            elif parse_int(c["raw"]) is None:
                c["reasons"].append(f"숫자 형식이 아님: '{c['raw']}'")

    # 자동 의심 규칙 2: 날짜 라벨이 기대한 순서와 같은지
    seq = SPEC["label_seq"]
    if seq:
        j = 0
        for rc in body:
            lab = rc[0]
            if lab["kind"] == "section":
                j = 0
                continue
            if j < len(seq) and label_key(lab["raw"]) != label_key(seq[j]):
                lab["reasons"].append(f"날짜 라벨이 기대 순서와 다름 (기대: '{seq[j]}')")
                lab["hint"] = f"{seq[j]} ← 날짜 순서로 본 값 (추정, 원본 대조 필요)"
            j += 1

    # 자동 의심 규칙 3: 합계 검산 (원시값 기준)
    instances = check_instances(byid, len(body))
    raw_checks = []
    for ins in instances:
        P = parse_int(byid[ins["parent"]]["raw"])
        kids = [byid[k] for k in ins["children"]]
        vals = [parse_int(k["raw"]) for k in kids]
        if P is None:
            continue
        s = sum(v or 0 for v in vals)
        raw_checks.append({"scope": ins["scope"], "check": ins["name"], "parent": P,
                           "children_sum": s, "diff": P - s, "pass": s == P})
        if s != P:
            hints = propose(P, vals, [k["raw"] for k in kids])
            msg = f"합계 불일치: {ins['name']} (총합 {P:,} vs 합 {s:,}, 차이 {P - s:+,})"
            allc = {-1: byid[ins["parent"]], **{i: k for i, k in enumerate(kids)}}
            targets = list(hints) or list(allc)
            for i in targets:
                allc[i]["reasons"].append(msg if hints else msg + " — 원인 칸 불명")
                if i in hints:
                    allc[i]["hint"] = f"{hints[i][0]:,} ← {hints[i][1]} (추정, 원본 대조 필요)"

    # 사람 대조 결과(corrections.json) 반영 -> 최종값/상태
    for c in cells:
        cr = corr.get(c["id"])
        numeric = c["kind"] == "value"
        raw_val = parse_int(c["raw"]) if numeric else c["raw"]
        c["footnote"] = None
        c["evidence"] = c["note"] = ""
        if cr is not None:
            c["footnote"] = cr.get("footnote")
            v = cr.get("value", c["raw"])
            if numeric:
                v = parse_int(str(v)) if str(v).strip() != "" else None
            c["final"] = v
            if numeric and v is None:
                c["status"] = "source_empty"
            elif v == raw_val:
                c["status"] = "confirmed"
            else:
                c["status"] = "corrected"
            c["evidence"] = cr.get("evidence", "")
            c["note"] = cr.get("note", "")
            if cr.get("flag"):  # 검토자가 '확인 필요'로 표시한 칸 — 값은 확정하지 않는다
                c["status"] = "needs_check"
                c["final"] = None if numeric else c["raw"]
                c["reasons"].append("검토자 표시: " + (c["evidence"] or c["note"] or "확인 필요"))
        elif c["reasons"]:
            c["status"] = "needs_check"
            c["final"] = None if numeric else c["raw"]
        elif numeric and is_blank(c["raw"]):
            c["status"] = "source_empty"
            c["final"] = None
            c["evidence"] = "자동: 해당 행의 합계 검산이 맞아 원본에도 값이 없는 칸으로 봄"
        else:
            c["status"] = "auto_ok"
            c["final"] = raw_val
            if c["kind"] in ("label", "section"):
                c["final"] = label_norm(raw_val)

    # 최종값 합계 검산
    final_checks = []
    for ins in instances:
        pc = byid[ins["parent"]]
        kids = [byid[k] for k in ins["children"]]
        if pc["final"] is None or any(k["status"] == "needs_check" for k in kids + [pc]):
            final_checks.append({"scope": ins["scope"], "check": ins["name"], "result": "미검증 (확인 필요 칸 있음)"})
            continue
        s = sum(k["final"] or 0 for k in kids)
        final_checks.append({"scope": ins["scope"], "check": ins["name"], "parent": pc["final"],
                             "children_sum": s, "diff": pc["final"] - s,
                             "result": "일치" if s == pc["final"] else "불일치"})

    review = {"table": SPEC["key"], "image": "table-crop.png", "structure_ok": structure_ok,
              "spans": [dict(sp) for sp in tb.get("spans", [])],
              "warnings": tb.get("warnings", []), "cells": cells,
              "raw_checks": raw_checks, "final_checks": final_checks}
    dump(OUT / "review.json", review)

    write_csv(body)
    write_overlay(cells)
    write_document(cells, body, review)
    write_manifest(meta, review)
    left = [c["id"] for c in cells if c["status"] == "needs_check"]
    n = {s: sum(c["status"] == s for c in cells) for s in
         ("auto_ok", "confirmed", "corrected", "source_empty", "needs_check")}
    print("구조:", "정상" if structure_ok else f"예상과 다름 (열 {tb['ncols']}, 행 {len(tb['rows'])})")
    print("셀 상태:", n)
    print("확인 필요 남음:", left or "없음")


def write_csv(body):
    cf = SPEC["csv"]
    head = (["section"] if cf["section"] else []) + cf["cols"] + (["footnotes"] if cf["footnotes"] else []) + ["needs_check"]
    rows, section = [], ""
    for rc in body:
        lab = rc[0]
        if lab["kind"] == "section":
            section = lab["final"] or lab["raw"]
            continue
        fn, chk = [], []
        for c in rc:
            if c["footnote"]:
                fn.append(f"{SPEC['cols'][c['col']][0]}:{c['footnote']}")
            if c["status"] == "needs_check":
                chk.append(SPEC["cols"][c["col"]][0])
        vals = [lab["final"] or ""] + ["" if c["final"] is None else c["final"] for c in rc[1:]]
        rows.append(([section] if cf["section"] else []) + vals + ([";".join(fn)] if cf["footnotes"] else []) + [";".join(chk)])
    with open(OUT / "table.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


COLORS = {"needs_check": (220, 38, 38), "corrected": (234, 138, 0), "confirmed": (37, 99, 235),
          "auto_ok": (22, 163, 74), "source_empty": (124, 58, 237)}
LABELS = {"needs_check": "확인 필요", "corrected": "수정함", "confirmed": "원본 대조 일치",
          "auto_ok": "자동 통과(규칙 기반)", "source_empty": "원본에 값 없음"}


def write_overlay(cells):
    base = Image.open(OUT / "table-crop.png").convert("RGB")
    img = Image.new("RGB", (base.width, base.height + 30), "white")
    img.paste(base, (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    f = font(12)
    byid = {c["id"]: c for c in cells}
    many = SPEC["key"] == "fraser"  # 칸이 너무 많은 표는 규칙 통과 칸 표시를 생략
    for c in cells:
        box = c["box"]
        if box is None and c["status"] == "source_empty" and c["kind"] == "value" and not many:
            lab, nb = byid.get(f"R{c['row']}C0"), byid.get(f"R{c['row'] - 1}C{c['col']}")
            if lab and lab["box"] and nb and nb["box"]:
                box = [nb["box"][0], lab["box"][1], nb["box"][2], lab["box"][3]]
        if not box or (many and c["status"] in ("auto_ok", "source_empty")):
            continue
        x0, y0, x1, y1 = box
        col = COLORS[c["status"]]
        loud = c["status"] not in ("confirmed", "auto_ok")
        d.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=col + (255,), width=3 if loud else 1,
                    fill=col + (40,) if loud else None)
        if loud:
            d.text((x0, max(0, y0 - 14)), c["id"], fill=col + (255,), font=f)
    x, H = 10, img.height
    for s in ("needs_check", "corrected", "confirmed", "auto_ok", "source_empty"):
        if many and s in ("auto_ok", "source_empty"):
            continue
        d.rectangle([x, H - 22, x + 12, H - 10], fill=COLORS[s] + (255,))
        d.text((x + 16, H - 24), LABELS[s], fill=(30, 30, 30, 255), font=font(12))
        x += 16 + len(LABELS[s]) * 13 + 24
    img.save(OUT / "review_overlay.png")


def write_document(cells, body, review):
    byid = {c["id"]: c for c in cells}
    raw_checks, final_checks = review["raw_checks"], review["final_checks"]
    spans = review["spans"]
    hdr = [byid.get(f"H0C{k}") for k in range(SPEC["ncols"])]
    sup = SPEC["sup"]
    L = []
    L.append(f"# {SPEC['title']}\n")
    S = SPEC["source"]
    L.append(f"- 출처: {S['publisher']}, {S['document']} · PDF {S['pdf_page']}쪽 · 인쇄 {S['printed_page']}쪽")
    L.append(f"- 이용 조건: {S['license']}")
    L.append(f"- 입력: `input/{INPUT.name}` (사본 `{OUT.relative_to(ROOT).as_posix()}/input_{INPUT.name}`)")
    L.append("- 처리: PaddleOCR(영어)로 글자·좌표를 읽고, 좌표·괘선으로 행·열을 묶어 표를 만든 뒤 원본과 대조")
    L.append("- 표기: 값 뒤 `✎` = 원시 OCR을 원본 대조 후 수정, `⚠` = 확인 필요(미해결)" +
             (", 각주 번호는 ¹ ²처럼 표시" if sup else "") + "\n")
    if not review["structure_ok"]:
        L.append("> ⚠ 표 구조(열·행 수)가 예상과 달라 아래 표는 신뢰할 수 없습니다.\n")
    for w in review["warnings"]:
        L.append(f"> ⚠ {w}\n")

    cap = [c for c in cells if c["kind"] == "caption"]
    if cap:
        L.append("**" + " ".join((c["final"] or c["raw"]) for c in cap) + "**\n")

    L.append("## 복원한 표\n")
    names = []
    for k, h in enumerate(hdr):
        nm = (h["final"] or h["raw"]).replace("\n", " ") if h else SPEC["cols"][k][1]
        sp = next((s for s in spans if s["c0"] <= k <= s["c1"]), None)
        if sp:
            sc = next((c for c in cells if c["kind"] == "span" and c["raw"] == sp["text"]), None)
            nm = f"{(sc['final'] if sc and sc['final'] else sp['text'])} / {nm}"
        names.append(nm)
    L.append("| " + " | ".join(names) + " |")
    L.append("|---|" + "---:|" * (SPEC["ncols"] - 1))

    def show(c):
        if c["kind"] in ("label", "section"):
            s = c["final"] or ""
            if c["kind"] == "section":
                return f"**{s}**"
            return ("　" if c["row"] in SPEC["indent_rows"] else "") + s + \
                   (" ✎" if c["status"] == "corrected" else "") + (" ⚠" if c["status"] == "needs_check" else "")
        if c["status"] == "needs_check":
            return "⚠ 확인 필요"
        if c["status"] == "source_empty":
            return "—"
        s = fmt(c["final"])
        if c["footnote"]:
            s += sup.get(c["footnote"], f"^{c['footnote']}")
        if c["status"] == "corrected":
            s += " ✎"
        return s

    for rc in body:
        row = [show(c) for c in rc]
        row += [""] * (SPEC["ncols"] - len(row))
        L.append("| " + " | ".join(row) + " |")
    L.append("")
    for n in [c for c in cells if c["kind"] == "note"]:
        L.append(f"- {n['final']}")
    L.append("\n> " + SPEC["blank_note"] + "\n")

    L.append("## 검토 기록 — 원시 인식 vs 원본 대조\n")
    L.append("(수정·특이 사항만 표시. 규칙으로 통과한 칸과 단순 일치 칸은 `review.json`에 모두 기록)\n")
    L.append("| 칸 | 행 이름 / 열 제목 | 원시 OCR | 최종 | 상태 | 근거·메모 |")
    L.append("|---|---|---|---|---|---|")
    for c in cells:
        generic = c["evidence"].startswith(("원본과 1:1", "자동:"))
        if c["status"] == "auto_ok" or (c["status"] in ("confirmed", "source_empty") and generic):
            continue
        fin = "—(비어 있음)" if c["status"] == "source_empty" else ("(미해결)" if c["final"] is None else
              (fmt(c["final"]) if c["kind"] == "value" else str(c["final"]).replace("\n", " ")))
        why = c["evidence"] or c["note"] or "; ".join(c["reasons"])
        if c["status"] == "needs_check" and c["hint"]:
            why += f" · 힌트: {c['hint']}"
        L.append(f"| {c['id']} | {(c['row_label'] or '').replace(chr(10), ' ')} / {c['col_title'] or c['kind']} | "
                 f"`{c['raw'].replace(chr(10), ' ')}` | {fin} | {LABELS[c['status']]} | {why} |")
    L.append("")

    L.append("## 합계·순서 검산\n")
    fails = [ck for ck in raw_checks if not ck["pass"]]
    L.append(f"원시 OCR 값 기준: 검산 {len(raw_checks)}건 중 **불일치 {len(fails)}건** (불일치는 오인식 의심 칸을 찾는 단서로 사용)\n")
    if fails:
        L.append("| 범위 | 검산 | 총합 | 자식 합 | 차이 |")
        L.append("|---|---|---:|---:|---:|")
        for ck in fails:
            L.append(f"| {ck['scope']} | {ck['check']} | {ck['parent']:,} | {ck['children_sum']:,} | {ck['diff']:+,} |")
        L.append("")
    ok = sum(ck["result"] == "일치" for ck in final_checks)
    bad = [ck for ck in final_checks if ck["result"] != "일치"]
    L.append(f"수정 반영 후 최종값 기준: 검산 {len(final_checks)}건 중 **일치 {ok}건**" +
             (f", 그 외 {len(bad)}건" if bad else "") + "\n")
    for ck in bad:
        L.append(f"- {ck['scope']} · {ck['check']}: {ck['result']}")
    if SPEC["label_seq"]:
        seq_bad = [c for c in cells if c["kind"] == "label" and any("기대 순서" in r for r in c["reasons"])]
        L.append(f"- 날짜 라벨을 기대 순서(구역별 24개 월말 날짜)와 비교: 원시 OCR 기준 불일치 {len(seq_bad)}칸"
                 + (" → " + ", ".join(c["id"] for c in seq_bad) if seq_bad else ""))
    L.append("")

    pending = [c for c in cells if c["status"] == "needs_check"]
    auto = [c for c in cells if c["status"] == "auto_ok"]
    auto_empty = [c for c in cells if c["status"] == "source_empty" and c["evidence"].startswith("자동:")]
    L.append("## 범위와 한계 (정직성 메모)\n")
    L.append(f"- 확인 필요(미해결) 칸: {', '.join(c['id'] for c in pending) if pending else '없음'}")
    L.append(f"- 사람 대조 기록이 없는 규칙 통과(`auto_ok`) 칸: {len(auto)}개" +
             (f", 자동 판정 빈 칸: {len(auto_empty)}개" if auto_empty else "") +
             ". 신뢰도·형식·합계(·날짜 순서) 규칙만 통과한 값입니다. 규칙은 합계가 우연히 맞는 오류나 "
             "신뢰도가 높은 오인식(예: 각주 연도 `1912`→`1012`)을 못 잡을 수 있어 확정값으로 보면 안 됩니다.")
    L.append("- 대조는 코딩 에이전트(Claude)가 원본 이미지를 보고 1차로 수행했습니다. 제출자(사람)의 재확인이 필요하며, "
             "의심 가는 칸은 `/review`에서 '확인 필요로 표시'하면 `table.csv`의 `needs_check` 열과 이 문서에 반영됩니다.")
    L.append("- 합계 역산·정규화·날짜 순서로 얻은 값은 '힌트'일 뿐이며, 원본 이미지와 대조한 뒤에만 `corrections.json`에 반영했습니다.")
    if SPEC["label_seq"]:
        L.append("- 날짜 라벨의 `Jan.31`→`Jan. 31` 같은 공백 정리는 형식 정리일 뿐 글자는 바꾸지 않습니다.")
    for t in SPEC["extra_limits"]:
        L.append(f"- {t}")
    L.append("\n## 파일\n")
    L.append("`table.csv`(최종 표) · `review.json`(칸별 원시값·좌표·상태) · `review_overlay.png`(원본 위 검토 표시) · "
             "`raw_ocr.json`·`ocr_lines.json`·`ocr_overlay.png`(원시 OCR) · `corrections.json`(사람 대조 기록) · `manifest.json`")
    (OUT / "document.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def pkg(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def write_manifest(meta, review):
    im = Image.open(INPUT)
    files = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "manifest.json")
    m = {
        "task": "OCR 표 이미지 문서화 (선택 과제 B)",
        "table": SPEC["key"],
        "source": SPEC["source"],
        "input": {"path": f"input/{INPUT.name}", "sha256": sha256(INPUT),
                  "size_px": list(im.size), "crop_box_xyxy": list(SPEC["crop"]) if SPEC["crop"] else None},
        "ocr": meta,
        "packages": {n: pkg(n) for n in ("paddleocr", "paddlepaddle", "paddlex", "opencv-python-headless",
                                          "opencv-contrib-python", "numpy", "pillow", "openpyxl", "flask")},
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "executed_where": "로컬 PC (Windows, CPU 전용, 외부 서버로 이미지 전송 없음)"},
        "review": {"thresholds": {"low_confidence": LOW_CONF},
                   "status_counts": {s: sum(c["status"] == s for c in review["cells"]) for s in
                                      ("auto_ok", "confirmed", "corrected", "source_empty", "needs_check")},
                   "corrections_file": f"{OUT.relative_to(ROOT).as_posix()}/corrections.json",
                   "corrections_sha256": sha256(CORRECTIONS) if CORRECTIONS.exists() else None},
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "outputs": files,
    }
    dump(OUT / "manifest.json", m)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="census", choices=list(SPECS))
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    configure(a.table)
    if not a.build_only:
        stage_ocr(a.lang)
    stage_build()
