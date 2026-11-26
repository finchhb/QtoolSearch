"""
src/training.py - обучение парсера на примерах технолога с векторным поиском схожести (TF-IDF / Cosine Similarity).
"""
import csv
import logging
import math
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

from src.code_normalize import homoglyph_latin

logger = logging.getLogger(__name__)

PATH = os.path.join("data", "training_examples.csv")
MATERIALS_CSV = os.path.join("data", "materials.csv")
# порог косинусной близости для «похожего» запроса; настраивается без правки кода
try:
    SIM_THRESHOLD = min(1.0, max(0.0, float(os.environ.get("QTOOL_TRAIN_SIM_THRESHOLD", "0.35"))))
except ValueError:
    SIM_THRESHOLD = 0.35
# поля-поправки, которые влияют на поиск; comment — только для админки
TRAIN_FIELDS = ("correct_iso", "correct_operation", "correct_skus", "correct_shape", "correct_size", "correct_radius")
CORRECTION_FIELDS = TRAIN_FIELDS + ("comment",)
FIELDS = [
    "id", "ts", "query", "query_norm", "parser_iso", "parser_operation", "parser_top_skus",
    "correct_iso", "correct_operation", "correct_shape", "correct_size", "correct_radius",
    "correct_skus", "comment", "status", "rules_added"
]
SHAPE_OK = set("ABCDEFGHKLMOPRSTVW")
ISO_OK = {"P", "M", "K", "N", "S", "H"}
OP_OK = {"finishing", "semi_finishing", "roughing"}
_LATIN2CYR = str.maketrans("abcehkmoptxygd", "авсенкмортхугд")
_lock = threading.Lock()
_cache: Dict[str, Any] = {"mtime": 0.0, "rows": [], "index": None, "exact": None}


def normalize(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    # «велдон» и «weldon» — одно и то же слово: технолог может набрать в любой раскладке
    t = re.sub(r"\bвелдон", "weldon", t)
    t = re.sub(r"\bбт(?=\d)", "вт", t)
    t = t.translate(_LATIN2CYR)
    # визуальные двойники -> одна форма: «ГС4325» == «GC4325», «СNMG» == «CNMG»
    t = homoglyph_latin(t)
    t = re.sub(r"[^\w\-]+", " ", t, flags=re.U)
    return re.sub(r"\s+", " ", t).strip()


def _tokenize(text: str) -> List[str]:
    return [w for w in normalize(text).split() if len(w) > 1]


def _build_index(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    """TF-IDF векторы примеров: один раз на версию файла, а не на каждый запрос."""
    docs = [_tokenize(r["query"]) for r in rows]
    df: Dict[str, int] = {}
    for toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    n = len(rows)
    vecs = []
    for toks in docs:
        tf: Dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        v = {t: c * (math.log(n / df[t]) + 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    return {"df": df, "vecs": vecs, "n": n}


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
    except Exception as e:
        logger.warning("Таблица обучения %s не читается (%s); примеры не применяются", PATH, e)
        rows = []
    _cache.update(mtime=mt, rows=rows, index=None, exact=None)
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
    _cache.update(rows=rows, index=None, exact=None)


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
) -> Optional[Dict[str, str]]:
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
    # нечему учиться — не засоряем таблицу (валидация живёт здесь, а не в app.py)
    if not any(entry[k] for k in CORRECTION_FIELDS):
        return None
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


def _exact_match(query: str) -> Optional[Dict[str, str]]:
    """Точно тот же запрос (после нормализации), что и в примере технолога. O(1) по кэшу."""
    if os.environ.get("TRAINING_DISABLE") == "1":
        return None
    q_norm = normalize(query)
    if not q_norm:
        return None
    with _lock:
        rows = _read()
        exact = _cache.get("exact")
        if exact is None:
            exact = {}
            for r in rows:
                if r.get("status") != "rejected":
                    exact.setdefault(normalize(r.get("query") or ""), r)
            _cache["exact"] = exact
    return exact.get(q_norm)


def _vector_search(query: str) -> Optional[Dict[str, str]]:
    """Похожий запрос по TF-IDF / cosine similarity среди примеров с поправками."""
    if os.environ.get("TRAINING_DISABLE") == "1":
        return None
    q_tokens = _tokenize(query)
    if not q_tokens:
        return None
    with _lock:
        rows = [r for r in _read()
                if r.get("status") != "rejected" and any(r.get(k) for k in TRAIN_FIELDS)]
        index = _cache.get("index")
        if index is None:
            # индекс строится по тому же отфильтрованному списку, по которому идёт оценка
            index = _build_index(rows)
            _cache["index"] = index
    if not rows:
        return None
    df, vecs, total_docs = index["df"], index["vecs"], index["n"]
    tf: Dict[str, int] = {}
    for t in q_tokens:
        tf[t] = tf.get(t, 0) + 1
    q_vec: Dict[str, float] = {}
    norm_sq = 0.0
    for t, c in tf.items():
        val = c * (math.log(total_docs / df.get(t, 1)) + 1.0)
        q_vec[t] = val
        norm_sq += val * val
    norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
    q_vec = {k: w / norm for k, w in q_vec.items()}

    best_match = None
    best_score = 0.0
    for idx, r in enumerate(rows):
        d_vec = vecs[idx]
        score = sum(q_vec[t] * d_vec[t] for t in q_vec if t in d_vec)
        if score > best_score:
            best_score = score
            best_match = r

    if best_match and best_score >= SIM_THRESHOLD:
        return best_match
    return None


def lookup(query: str) -> Optional[Dict[str, str]]:
    """Сначала точное совпадение запроса, затем векторный поиск похожего."""
    return _exact_match(query) or _vector_search(query)


def lookup_exact(query: str) -> Optional[Dict[str, str]]:
    """Точно тот же запрос, что и в примере технолога: только для него ответ считаем эталонным."""
    return _exact_match(query)


def split_skus(value: str) -> List[str]:
    """«BT40-SL20-10; BT40-SL20-90» -> список позиций из ответа технолога."""
    return [s.strip() for s in re.split(r"[;,\n]+", value or "") if s.strip()]


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
