"""PaddleOCR 웹 서비스: 이미지 업로드 -> OCR -> 결과 저장/다운로드."""
import os
import json
import re
import uuid
import csv
import io
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from flask import Flask, jsonify, request, send_from_directory, abort, Response

BASE = Path(__file__).parent
UPLOADS = BASE / "uploads"
RESULTS = BASE / "results"
UPLOADS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)

ALLOWED = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

from ocrlib import get_ocr, run_ocr, build_table, table_matrix, table_xlsx, detect_hrules

# ---------------------------------------------------------------- 표 검토 (Census Table 1 / FRASER No. 11)
OCR_DIRS = {"census": BASE / "outputs" / "ocr", "fraser": BASE / "outputs" / "ocr-fraser"}


def _table():
    t = request.args.get("table") or (request.get_json(silent=True) or {}).get("table") or "census"
    if t not in OCR_DIRS:
        abort(404)
    return t, OCR_DIRS[t]


def _rebuild(t):
    import run_ocr
    run_ocr.configure(t)
    run_ocr.stage_build()


@app.get("/review")
def review_page():
    return send_from_directory(app.static_folder, "review.html")


def _review_json(t, d):
    p = d / "review.json"
    if not p.exists():
        return jsonify(error=f"{p.name} 이 없습니다. python run_ocr.py --table {t} 를 먼저 실행하세요."), 404
    r = json.loads(p.read_text(encoding="utf-8"))
    r["corrections"] = json.loads((d / "corrections.json").read_text(encoding="utf-8"))         if (d / "corrections.json").exists() else {}
    r["table"] = t
    return jsonify(r)


@app.get("/api/review")
def api_review():
    t, d = _table()
    return _review_json(t, d)


@app.post("/api/review/cell")
def api_review_cell():
    """칸 하나의 검토 결과 저장: mode = confirm | correct | flag | clear"""
    t, d = _table()
    b = request.get_json(force=True)
    cid, mode = b.get("id", ""), b.get("mode")
    if not re.fullmatch(r"([HRNSC]\d+(C\d+)?)", cid):
        return jsonify(error="잘못된 칸 ID"), 400
    cf = d / "corrections.json"
    corr = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {}
    review = json.loads((d / "review.json").read_text(encoding="utf-8"))
    cell = next((c for c in review["cells"] if c["id"] == cid), None)
    if cell is None:
        return jsonify(error="없는 칸"), 404
    ev = (b.get("evidence") or "").strip()
    fn = (b.get("footnote") or "").strip() or None
    if mode == "clear":
        corr.pop(cid, None)
    elif mode == "flag":
        corr[cid] = {"flag": True, "evidence": ev or "원본 대조 필요", "value": cell["raw"]}
    elif mode in ("confirm", "correct"):
        val = cell["raw"] if mode == "confirm" else str(b.get("value", ""))
        if cell["kind"] == "value" and mode == "correct" and val.strip():
            val = re.sub(r"[,\s]", "", val)
            if not val.isdigit():
                return jsonify(error="숫자만 입력하세요 (비어 있으면 '원본에 값 없음')"), 400
        if mode == "confirm" and cell["kind"] == "value":
            val = re.sub(r"[,\s]", "", val)
        if mode == "correct" and not ev:
            return jsonify(error="수정에는 근거(원본에서 무엇을 봤는지)를 적어 주세요."), 400
        corr[cid] = {"value": val, "evidence": ev or "원본 대조 일치"}
        if fn:
            corr[cid]["footnote"] = fn
    else:
        return jsonify(error="mode 오류"), 400
    cf.write_text(json.dumps(corr, ensure_ascii=False, indent=2), encoding="utf-8")
    _rebuild(t)
    return _review_json(t, d)


@app.get("/outputs/<table>/<path:name>")
def ocr_output(table, name):
    d = {"ocr": OCR_DIRS["census"], "ocr-fraser": OCR_DIRS["fraser"]}.get(table)
    if d is None:
        abort(404)
    return send_from_directory(d, name)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/ocr")
def api_ocr():
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify(error="이미지 파일이 없습니다."), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED:
        return jsonify(error=f"지원하지 않는 형식입니다: {ext}"), 400
    lang = request.form.get("lang", "korean")
    if lang not in ("korean", "en"):
        lang = "korean"

    rid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    img_path = UPLOADS / f"{rid}{ext}"
    f.save(img_path)
    try:
        lines = run_ocr(img_path, lang)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"OCR 실패: {e}"), 500

    rules = detect_hrules(img_path)
    text = "\n".join(l["text"] for l in lines)
    record = {
        "id": rid,
        "filename": f.filename,
        "image": f"{rid}{ext}",
        "lang": lang,
        "created": datetime.now().isoformat(timespec="seconds"),
        "text": text,
        "lines": lines,
        "rules": rules,
        "table": build_table(lines, rules),
    }
    (RESULTS / f"{rid}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / f"{rid}.txt").write_text(text, encoding="utf-8")
    return jsonify(record)


_meta_cache = {}  # 경로 -> (수정시각, 요약) : 목록을 열 때마다 큰 JSON을 다시 읽지 않기 위함


def _meta(p):
    m = p.stat().st_mtime
    hit = _meta_cache.get(p)
    if hit and hit[0] == m:
        return hit[1]
    d = json.loads(p.read_text(encoding="utf-8"))
    s = {k: d[k] for k in ("id", "filename", "created", "lang")} | {"chars": len(d["text"])}
    _meta_cache[p] = (m, s)
    return s


@app.get("/api/results")
def api_results():
    return jsonify([_meta(p) for p in sorted(RESULTS.glob("*.json"), reverse=True)])


@app.get("/api/results/<rid>")
def api_result(rid):
    p = RESULTS / f"{Path(rid).name}.json"
    if not p.exists():
        abort(404)
    d = json.loads(p.read_text(encoding="utf-8"))
    d["table"] = build_table(d["lines"], d.get("rules"))
    return jsonify(d)


@app.delete("/api/results/<rid>")
def api_delete(rid):
    rid = Path(rid).name
    d = RESULTS / f"{rid}.json"
    if not d.exists():
        abort(404)
    img = json.loads(d.read_text(encoding="utf-8"))["image"]
    d.unlink()
    (RESULTS / f"{rid}.txt").unlink(missing_ok=True)
    (UPLOADS / img).unlink(missing_ok=True)
    return jsonify(ok=True)


@app.get("/download/<rid>.<fmt>")
def download(rid, fmt):
    if fmt in ("xlsx", "csv"):
        p = RESULTS / f"{Path(rid).name}.json"
        if not p.exists():
            abort(404)
        _d = json.loads(p.read_text(encoding="utf-8"))
        tb = build_table(_d["lines"], _d.get("rules"))
        if fmt == "xlsx":
            data, mime = table_xlsx(tb), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            buf = io.StringIO()
            csv.writer(buf).writerows(table_matrix(tb))
            data, mime = ("﻿" + buf.getvalue()).encode("utf-8"), "text/csv"
        return Response(data, mimetype=mime,
                        headers={"Content-Disposition": f"attachment; filename={Path(rid).name}.{fmt}"})
    if fmt not in ("txt", "json"):
        abort(404)
    return send_from_directory(RESULTS, f"{Path(rid).name}.{fmt}", as_attachment=True)


@app.get("/uploads/<name>")
def uploaded(name):
    return send_from_directory(UPLOADS, Path(name).name)


if __name__ == "__main__":
    import threading
    # 모델은 백그라운드에서 미리 불러온다 (서버는 바로 열리고, 첫 변환만 로딩이 끝나길 기다린다)
    threading.Thread(target=lambda: get_ocr("en"), daemon=True).start()
    print("http://127.0.0.1:5000 에서 접속하세요 (OCR 모델은 백그라운드에서 로딩 중)")
    app.run(host="127.0.0.1", port=5000, debug=False)
