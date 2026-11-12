"""
src/iso1832.py — детерминированный разбор обозначений сменных пластин ISO 1832 (ГОСТ 19042-80).
Таблицы: табл.1 (формы), табл.2 (задние углы), табл.6а (код размера -> диаметр вписанной окружности),
табл.6б (толщина), прил.9 (метрические круглые). Источник: ГОСТ 19042-80 (ИСО 1832-85).
Без LLM: только таблицы и регулярные выражения. Неоднозначности помечаются, не угадываются.
"""
import math
import re
from typing import Any, Dict, List, Optional, Tuple

SHAPES = {
    "A": (85, "параллелограмм 85°"), "B": (82, "параллелограмм 82°"),
    "C": (80, "ромб 80°"), "D": (55, "ромб 55°"), "E": (75, "ромб 75°"),
    "M": (86, "ромб 86°"), "V": (35, "ромб 35°"), "K": (55, "параллелограмм 55°"),
    "F": (84, "параллелограмм 84°"), "H": (120, "шестигранник"), "O": (135, "восьмигранник"),
    "P": (108, "пятигранник"), "R": (None, "круглая"), "S": (90, "квадрат"),
    "T": (60, "треугольник"), "W": (80, "тригон 80°"), "L": (90, "прямоугольная"),
}
_D = [3.97, 4.76, 5.56, 6.35, 7.94, 9.525, 12.7, 15.875, 19.05, 25.4, 31.75]
_ROWS = {
    "S": ["03","04","05","06","07","09","12","15","19","25","31"],
    "T": ["06","08","09","11","13","16","22","27","33","44","54"],
    "C": ["04","04","05","06","08","09","12","16","19","25","32"],
    "D": [None,"05","06","07","09","11","15","19","23","31","38"],
    "E": [None,"04","05","06","08","09","13","16","19","26","32"],
    "M": [None,"04","05","06","07","09","12","15","19","25","31"],
    "V": [None,"08","09","11","13","16","22","27","33","44","54"],
    "W": [None,None,"03","04","05","06","08","10","13","17","21"],
    "R": [None,None,None,"06","07","09","12","15","19","25","31"],
    "H": [None,None,None,"03","04","05","07","09","11","14","18"],
    "O": [None,None,None,"02","03","04","05","06","07","10","13"],
    "P": [None,None,None,"04","05","07","09","11","13","18","23"],
}
SIZE2D: Dict[Tuple[str, str], List[float]] = {}
for _sh, _codes in _ROWS.items():
    for _d, _c in zip(_D, _codes):
        if _c:
            SIZE2D.setdefault((_sh, _c), []).append(_d)
ALL_SIZE_CODES = {c for _, c in SIZE2D}
R_METRIC = {"06": 6.0, "08": 8.0, "10": 10.0, "12": 12.0, "16": 16.0, "20": 20.0, "25": 25.0, "32": 32.0}
THICK = {"01": 1.59, "T1": 1.98, "02": 2.38, "03": 3.18, "T3": 3.97, "04": 4.76,
         "05": 5.56, "06": 6.35, "07": 7.94, "08": 8.0, "09": 9.52, "12": 12.7}
RELIEF = {"A": 3, "B": 5, "C": 7, "D": 15, "E": 20, "F": 25, "G": 30, "N": 0, "P": 11}
RELIEF_BY_DEG = {v: k for k, v in RELIEF.items()}
RU_SHAPE = [
    ("ломаный треугольн", ["W"]), ("тригон", ["W"]),
    ("ромб", ["C", "D", "V", "E", "M"]),
    ("треугольн", ["T"]), ("трехгран", ["T"]), ("треух", ["T"]),
    ("квадрат", ["S"]), ("четырехгран", ["S"]),
    ("кругл", ["R"]), ("шестигран", ["H", "W"]), ("восьмигран", ["O"]),
    ("пятигран", ["P"]), ("прямоугольн", ["L"]), ("параллелограмм", ["A", "B", "K", "F"]),
]
_ANGLE_RE = re.compile(r"(?<![\d.,])(108|120|135|35|55|75|80|86|85|82|84|90|45|60)\s*(?:°|град)")
_HOMO = str.maketrans("АВСЕНКМОРТХУавсенкмортху", "ABCEHKMOPTXYabcehkmoPTxy")

def norm_code(text: str) -> str:
    s = (text or "").translate(_HOMO).upper()
    return re.sub(r"O(?=\d)", "0", s)

ISO_RE = re.compile(
    r"\b([ABCDEFGHKLMOPRSTVW])([ABCDEGFNP])([ACEFGHJKLMNU])([NRFAMGWTQUBHCJX])"
    r"[-\s]?(\d{2})(T\d|\d{2})(\d{2}|M0|MO)([RL])?(?![0-9A-Z])")
PARTIAL_RE = re.compile(
    r"\b([ABCDEFGHKLMOPRSTVW])([ABCDEGFNP])([ACEFGHJKLMNU])([NRFAMGWTQUBHCJX])[-\s]?(\d{1,5}(?:T\d)?)?(?![0-9A-Z])")

def edge_len(shape, d):
    a = SHAPES[shape][0]
    if shape in ("C","D","E","M","V","A","B","K","F"):
        return d / math.sin(math.radians(a))
    n = {"T":3,"S":4,"P":5,"H":6,"O":8}.get(shape)
    return d * math.tan(math.pi / n) if n else None

def resolve_size(shape, code, corner=None):
    warn = []
    if shape == "R":
        if corner in ("M0","MO"):
            return ([R_METRIC[code]] if code in R_METRIC else []), warn
        if corner == "00":
            return list(SIZE2D.get(("R", code), [])), warn
        cand = list(dict.fromkeys(SIZE2D.get(("R", code), []) + ([R_METRIC[code]] if code in R_METRIC else [])))
        if len(cand) > 1:
            warn.append(f"Круглая {code}: метрический/дюймовый ряд не различить без M0/00")
        return cand, warn
    cand = SIZE2D.get((shape, code), [])
    if len(cand) > 1:
        warn.append(f"{shape}{code}: стандарт допускает d={cand} — уточните")
    return list(cand), warn

def parse_code(token):
    m = ISO_RE.search(norm_code(token))
    if not m:
        return None
    sh, rel, tol, typ, size, th, corner, hand = m.groups()
    d, warn = resolve_size(sh, size, corner)
    r = None if corner in ("M0","MO") else (0.0 if corner == "00" else int(corner) / 10.0)
    return {"code": m.group(0).replace(" ","").replace("-",""), "shape": sh, "relief": rel,
            "tolerance": tol, "type": typ, "size_code": size, "thickness_code": th,
            "thickness": THICK.get(th), "corner_code": corner, "corner_r": r, "hand": hand or "",
            "ic_d": d[0] if len(d) == 1 else None, "ic_candidates": d, "warnings": warn}

def find_codes(text):
    out = []
    for m in ISO_RE.finditer(norm_code(text)):
        p = parse_code(m.group(0))
        if p:
            p["span"] = m.span(); out.append(p)
    return out

def detect_shape(text):
    codes = find_codes(text)
    if codes:
        s = codes[0]["shape"]; return s, [s], SHAPES[s][0]
    t = (text or "").lower().replace("ё","е")
    if "ломан" in t and "треугольн" in t:
        return "W", ["W"], 80
    cands = []
    for stem, letters in RU_SHAPE:
        if stem in t:
            for L in letters:
                if L not in cands: cands.append(L)
    ang = None
    m = _ANGLE_RE.search(t)
    if m:
        ang = int(m.group(1))
    else:
        m2 = re.search(r"(?:ромб\w*|параллелограмм\w*)\s+(\d{2})(?!\d)", t)
        if m2: ang = int(m2.group(1))
    if ang is not None:
        narrowed = [L for L in cands if SHAPES[L][0] == ang]
        if narrowed: cands = narrowed
        elif not cands: cands = [L for L,(a,_) in SHAPES.items() if a == ang]
    if len(cands) == 1:
        return cands[0], cands, ang
    return "", cands, ang

def detect_clearance(text):
    codes = find_codes(text)
    if codes: return codes[0]["relief"]
    t = (text or "").lower()
    m = re.search(r"задн\w*\s+угол\s*[:=]?\s*(\d{1,2})(?!\d)", t)
    if m and int(m.group(1)) in RELIEF_BY_DEG: return RELIEF_BY_DEG[int(m.group(1))]
    m = re.search(r"(?<![\d.,])(0|3|5|7|11|15|20|25|30)\s*(?:°|град)", t)
    if m: return RELIEF_BY_DEG[int(m.group(1))]
    if any(w in t for w in ("негативн","двухсторонн","двусторонн","без заднего угла")): return "N"
    if any(w in t for w in ("позитивн","односторонн")): return "C"
    return ""

def detect_radius(text):
    codes = find_codes(text)
    if codes: return codes[0]["corner_r"]
    t = (text or "").lower().replace(",", ".")
    m = re.search(r"(?<![a-zа-я0-9])(?:r|радиус\w*)\s*[:=]?\s*(\d+(?:\.\d+)?)(?![\d])", t)
    if m:
        v = float(m.group(1))
        if v <= 3.2: return v
    m = re.search(r"(?<![a-zа-я0-9])r0(\d)(?![\d])", t)
    if m: return int(m.group(1)) / 10.0
    return None

def _ic_to_code(shape, ic):
    for (s, c), ds in SIZE2D.items():
        if s == shape and any(abs(d - ic) < 0.01 for d in ds): return c
    if shape == "R":
        for c, d in R_METRIC.items():
            if abs(d - ic) < 0.01: return c
    return None

def detect_size(text, shape=""):
    t = (text or "").lower().replace(",", ".")
    up = norm_code(text)
    out = {"size_code": "", "ic_d": None, "warnings": []}
    ang = detect_shape(text)[2]
    m = re.search(r"(?<![0-9A-Z])(\d{2})(T\d|\d{2})(\d{2})(?![0-9])", up)
    if m and m.group(2) in THICK and m.group(1) in ALL_SIZE_CODES:
        if not shape or (shape, m.group(1)) in SIZE2D or shape == "R":
            out["size_code"] = m.group(1)
            d, w = resolve_size(shape, m.group(1)) if shape else ([], [])
            if len(d) == 1: out["ic_d"] = d[0]
            out["warnings"] += w; return out
    m = re.search(r"(?<![0-9A-Z])(\d{2})(T\d|\d{2})(?![0-9])", up)
    if m and m.group(2) in THICK and m.group(1) in ALL_SIZE_CODES:
        if not shape or (shape, m.group(1)) in SIZE2D or shape == "R":
            out["size_code"] = m.group(1)
            d, w = resolve_size(shape, m.group(1)) if shape else ([], [])
            if len(d) == 1: out["ic_d"] = d[0]
            out["warnings"] += w; return out
    m = re.search(r"(?:\bd\s*[:=]?\s*|\bic\s*[:=]?\s*|вписанн\w*\s*|ø\s*|диаметр\w*\s*)(\d{1,2}(?:\.\d+)?)", t)
    if m:
        ic = float(m.group(1)); out["ic_d"] = ic
        if shape:
            c = _ic_to_code(shape, ic)
            if c: out["size_code"] = c
        return out
    m = re.search(r"(?:размер\w*|габарит\w*|кромк\w*)\s*[:=-]?\s*(\d{1,2})(?!\d)", t) or \
        re.search(r"(?<![\d.,])(\d{1,2})\s*(?:размер|габарит)", t)
    if m:
        code = f"{int(m.group(1)):02d}"; out["size_code"] = code
        if shape:
            d, w = resolve_size(shape, code)
            if len(d) == 1: out["ic_d"] = d[0]
            out["warnings"] += w
        return out
    m = re.search(r"(?:ромб\w*|треугольн\w*|треух\w*|квадрат\w*|тригон\w*|шестигран\w*|кругл\w*|пятигран\w*|восьмигран\w*)\s+(?:№\s*)?(\d{1,2})(?!\d)", t)
    if m:
        n = int(m.group(1)); code = f"{n:02d}"
        if shape and n != ang and ((shape, code) in SIZE2D or (shape == "R" and code in R_METRIC)):
            out["size_code"] = code
            d, w = resolve_size(shape, code)
            if len(d) == 1: out["ic_d"] = d[0]
            out["warnings"] += w; return out
    m = re.search(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*мм\b", t)
    if m:
        v = float(m.group(1))
        if v != int(v):
            out["ic_d"] = v
            if shape:
                c = _ic_to_code(shape, v)
                if c: out["size_code"] = c
            else:
                out["warnings"].append("Дробный размер в мм принят за диаметр вписанной окружности; укажите форму/угол")
            return out
        if shape and shape != "R":
            for (s, c), ds in SIZE2D.items():
                if s == shape:
                    for d in ds:
                        el = edge_len(shape, d)
                        if el is not None and int(el) == int(v):
                            out["size_code"] = c; out["ic_d"] = d
                            out["warnings"].append(f"{int(v)} мм — длина кромки по ГОСТ 19042-80 (d={d} мм)")
                            return out
        elif shape == "R":
            c = f"{int(v):02d}"
            if c in R_METRIC:
                out["size_code"] = c; out["ic_d"] = R_METRIC[c]; return out
    return out

QTY_RE = re.compile(r"(?:(\d+)\s*(?:шт\.?|штук|уп\.?|pcs?)\b|[xх*]\s*(\d+)\s*$)", re.I)

def split_positions(text):
    out = []
    for raw in re.split(r"[\n;|]+", text or ""):
        chunk = re.sub(r"^\s*\d+[.)]\s*", "", raw).strip()
        if not chunk: continue
        codes = list(ISO_RE.finditer(norm_code(chunk)))
        segs = []
        if len(codes) > 1:
            for i, m in enumerate(codes):
                end = codes[i+1].start() if i+1 < len(codes) else len(chunk)
                segs.append(chunk[m.start():end])
        else:
            segs = [chunk]
        for seg in segs:
            q = QTY_RE.search(seg)
            qty = int(next(g for g in q.groups() if g)) if q else None
            clean = (seg[:q.start()] + " " + seg[q.end():]).strip(" -/,") if q else seg.strip()
            if clean: out.append({"text": clean, "qty": qty})
    return out

def detect_all(text):
    codes = find_codes(text)
    p = codes[0] if codes else None
    shape, cands, ang = detect_shape(text)
    out = {"code": p["code"] if p else "", "shape": (p["shape"] if p else shape) or "",
           "shape_candidates": cands, "angle": ang,
           "clearance": (p["relief"] if p else detect_clearance(text)) or "",
           "size_code": (p["size_code"] if p else "") or "",
           "radius": p["corner_r"] if p else None,
           "ic_d": p["ic_d"] if p else None, "thickness": p["thickness"] if p else None,
           "warnings": list(p["warnings"]) if p else []}
    if not out["size_code"]:
        sz = detect_size(text, out["shape"])
        out["size_code"] = sz.get("size_code") or ""
        out["ic_d"] = out["ic_d"] if out["ic_d"] is not None else sz.get("ic_d")
        out["warnings"] += sz.get("warnings", [])
    if out["radius"] is None:
        out["radius"] = detect_radius(text)
    if out["radius"] is None and not p:
        m = re.search(r"(?<![0-9A-Z])(\d{2})(T\d|\d{2})(\d{2})(?![0-9])", norm_code(text))
        if m and m.group(2) in THICK and m.group(1) in ALL_SIZE_CODES:
            out["radius"] = int(m.group(3)) / 10.0
    if not p and not out["code"]:
        m = PARTIAL_RE.search(norm_code(text))
        if m:
            out["code"] = "".join(g for g in m.groups()[:5] if g)
            out["shape"] = out["shape"] or m.group(1)
            out["clearance"] = out["clearance"] or m.group(2)
    if not out["shape"] and cands:
        out["warnings"].append("Форма неоднозначна (" + "/".join(cands) + ") — уточните угол при вершине")
    return out