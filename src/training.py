"""
src/training.py - обучение парсера на примерах технолога с векторным поиском схожести (TF-IDF / Cosine Similarity).
"""
import csv
import math
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

PATH = os.path.join("data", "training_examples.csv")
MATERIALS_CSV = os.path.join("data", "materials.csv")
FIELDS = [
    "id", "ts", "query", "query_norm", "parser_iso", "parser_operation", "parser_top_skus",
    "correct_iso", "correct_operation", "correct_shape", "correct_size", "correct_radius",
    "correct_skus", "comment", "status", "rules_added"
]
SHAPE_OK = set("ABCDEFGHKLMOPRSTVW")
ISO_OK = {"P", "M", "K", "N", "S", "H"}
OP_OK = {"finishing", "semi_finishing", "roughing"}
_LATIN2CYR = str.maketrans("abcehkmoptxy", "авсенкмортху")
_lock = threading.Lock()
_cache: Dict[str, Any] = {"mtime": 0.0, "rows": []}


def normalize(text: str) -> str:
    t = (text or "").lower().replace("ё", "е").translate(_LATIN2CYR)
    t = re.sub(r"[^\w\-]+", " ", t, flags=re.U)
    return re.sub(r"\s+", " ", t).strip()


def _tokenize(text: str) -> List[str]:
    return [w for w in normalize(text).split() if len(w) > 1]


def _read() -> List[Dict[str, str]]:
    try:
        mt = os.path.getmtime(PATH)
    except OSError:
        return []
    if mt == _cache["mtime"]:
        return _cache["rows"]
    rows = []
    try:
        with open(PATH, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if (r.get("query") or "").strip():
                    rows.append({k: (r.get(k) or "") for k in FIELDS})
    except Exception:
        rows = []
    _cache.update(mtime=mt, rows=rows)
    return rows


def _write(rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    try:
        _cache["mtime"] = os.path.getmtime(PATH)
    except OSError:
        pass
    _cache["rows"] = rows


def list_examples(limit: int = 300) -> List[Dict[str, str]]:
    with _lock:
        return list(_read())[-limit:][::-1]


def count() -> int:
    with _lock:
        return len(_read())


def add_example(
    query: str,
    correct_iso: str = "",
    correct_operation: str = "",
    correct_skus: str = "",
    comment: str = "",
    parser: Optional[Dict[str, Any]] = None,
    correct_shape: str = "",
    correct_size: str = "",
    correct_radius: str = "",
    *args,
    **kwargs,
) -> Dict[str, str]:
    iso = (correct_iso or "").strip().upper()
    op = (correct_operation or "").strip().lower()
    op = {"medium": "semi_finishing"}.get(op, op)
    skus = "; ".join(s.strip() for s in re.split(r"[;,\n]+", correct_skus or "") if s.strip())[:500]
    sh = (correct_shape or "").strip().upper()
    sz = (correct_size or "").strip()
    rad = (correct_radius or "").strip().replace(",", ".")
    entry = {
        "id": "",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "query": (query or "").strip()[:500],
        "query_norm": normalize(query),
        "parser_iso": str((parser or {}).get("iso") or ""),
        "parser_operation": str((parser or {}).get("operation") or ""),
        "parser_top_skus": "; ".join((parser or {}).get("top_skus") or [])[:300],
        "correct_iso": iso if iso in ISO_OK else "",
        "correct_operation": op if op in OP_OK else "",
        "correct_shape": sh if sh in SHAPE_OK else "",
        "correct_size": sz.zfill(2) if (sz.isdigit() and len(sz) <= 2) else "",
        "correct_radius": rad if re.fullmatch(r"\d+(?:\.\d+)?", rad) else "",
        "correct_skus": skus,
        "comment": (comment or "").strip()[:600],
        "status": "new",
        "rules_added": "",
    }
    with _lock:
        rows = list(_read())
        rows = [r for r in rows if r["query_norm"] != entry["query_norm"]]
        entry["id"] = str(max([int(r["id"]) for r in rows if str(r["id"]).isdigit()] + [0]) + 1)
        rows.append(entry)
        _write(rows)
    return entry


def delete_example(ex_id: str) -> bool:
    with _lock:
        rows = list(_read())
        new = [r for r in rows if r["id"] != str(ex_id)]
        if len(new) == len(rows):
            return False
        _write(new)
        return True


def lookup(query: str) -> Optional[Dict[str, str]]:
    if os.environ.get("TRAINING_DISABLE") == "1":
        return None
    with _lock:
        rows = [
            r for r in _read()
            if r.get("status") != "rejected"
            and any(r.get(k) for k in ("correct_iso", "correct_operation", "correct_skus", "correct_shape", "correct_size", "correct_radius"))
        ]
    if not rows:
        return None

    q_norm = normalize(query)
    for r in rows:
        if r.get("query_norm") == q_norm:
            return r

    q_tokens = _tokenize(query)
    if not q_tokens:
        return None

    doc_tokens_list = [_tokenize(r["query"]) for r in rows]
    total_docs = len(rows)
    df: Dict[str, int] = {}
    for toks in doc_tokens_list:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1

    def get_vector(toks: List[str]) -> Dict[str, float]:
        v: Dict[str, int] = {}
        for t in toks:
            v[t] = v.get(t, 0) + 1
        norm_sq = 0.0
        res: Dict[str, float] = {}
        for t, tf in v.items():
            idf = math.log(total_docs / df.get(t, 1)) + 1.0
            val = tf * idf
            res[t] = val
            norm_sq += val * val
        norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
        return {k: w / norm for k, w in res.items()}

    q_vec = get_vector(q_tokens)
    best_match = None
    best_score = 0.0

    for idx, r in enumerate(rows):
        d_vec = get_vector(doc_tokens_list[idx])
        score = sum(q_vec[t] * d_vec[t] for t in q_vec if t in d_vec)
        if score > best_score:
            best_score = score
            best_match = r

    if best_match and best_score >= 0.35:
        return best_match
    return None


def suggest_tokens(query: str) -> List[str]:
    out = []
    stop = {
        "точение", "чистовое", "чистовая", "черновая", "черновое", "получистовая",
        "получистовое", "обработка", "пластина", "пластины", "подбери", "нужна",
        "нужно", "для", "по", "из", "под", "при", "без", "что", "как", "мм", "шт", "стали", "сталь"
    }
    for tok in re.findall(r"[0-9A-Za-zА-Яа-яЁё][0-9A-Za-zА-Яа-яЁё\-./]{1,}", query or ""):
        low = tok.lower().strip("-./")
        if len(low) < 3 or low in stop:
            continue
        if low not in out:
            out.append(low)
    return out[:8]


def _rule_regex(token: str) -> str:
    """Марка может быть набрана латиницей или кириллицей: g→г, d→д не переводятся normalize,
    поэтому в правиле допускаем оба варианта символа (иначе «GC4325» и «ГС4325» — разные правила)."""
    out = []
    for ch in token:
        alt = {"d": "д", "g": "г"}.get(ch)
        out.append(f"[{ch}{alt}]" if alt else re.escape(ch))
    return "".join(out)


def add_material_rules(tokens: List[str], iso: str, note: str = "") -> int:
    iso = (iso or "").strip().upper()
    if iso not in ISO_OK:
        return 0
    existing = ""
    if os.path.exists(MATERIALS_CSV):
        with open(MATERIALS_CSV, "r", encoding="utf-8-sig") as f:
            existing = f.read()
    added = 0
    lines = []
    for t in tokens:
        t = normalize(t).replace(" ", "")
        if len(t) < 3:
            continue
        esc = _rule_regex(t)
        pat = r"(?<![а-яa-z0-9])" + esc + r"(?![а-яa-z0-9])"
        if pat in existing:
            continue
        clean_note = (note or "добавлено по примеру технолога").replace('"', "")
        lines.append(f'"{pat}",{iso},"{clean_note}"')
        added += 1
    if lines:
        os.makedirs(os.path.dirname(MATERIALS_CSV), exist_ok=True)
        need_header = not existing.strip()
        with open(MATERIALS_CSV, "a", encoding="utf-8-sig", newline="") as f:
            if need_header:
                f.write("pattern,iso,note\n")
            elif not existing.endswith("\n"):
                f.write("\n")
            f.write("\n".join(lines) + "\n")
        try:
            from src.materials_mapping import reload_material_rules
            reload_material_rules()
        except Exception:
            pass
    return added
