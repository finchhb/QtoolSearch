"""
src/site_catalog.py - приём товарных таблиц qtool.ru и сборка единого каталога всех групп.

Конвейер: скачивание (условный GET + sha256) -> чтение всех листов -> определение раскладки ->
классификация раздела -> разбор атрибутов из колонок [ATT_*] и из названия -> валидация ->
снимок data/catalog_site.csv и манифест data/site_manifest.json (атомарная подмена).

Идентификатор позиции - ID элемента Битрикса (он же «Артикул товара» в общем прайсе).
По нему же из sitemap-iblock-28.xml подставляется настоящая ссылка на карточку товара.
"""
import csv
import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from build_catalog import parse_turning
from src.xlsx_reader import Sheet, find_header_row, header_index, read_workbook, schema_hash

DATA_DIR = os.environ.get("ADVISOR_DATA_DIR", "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SITE_CSV = os.path.join(DATA_DIR, "catalog_site.csv")
MANIFEST = os.path.join(DATA_DIR, "site_manifest.json")
URLS_JSON = os.path.join(DATA_DIR, "site_urls.json")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
QTOOL_BASE = "https://qtool.ru"
PLATES_TEMPLATE = QTOOL_BASE + "/upload/V/smennie_plastini_ISO_tochenie_{date}.xlsx"
PRICE_URLS = [QTOOL_BASE + "/downloads/price.xlsx", QTOOL_BASE + "/upload/price.xlsx"]
SITEMAP_CATALOG = QTOOL_BASE + "/sitemap-iblock-28.xml"

FIELDS = [
    "id", "sku", "name", "brand", "family", "category", "section", "subsection",
    "stock", "price", "currency", "price_on_request", "active", "url",
    "coating", "material", "size", "diameter_mm", "shank_mm", "length_mm", "cutting_length_mm",
    "teeth", "pitch_mm", "thread", "angle_deg", "radius_mm", "width_mm", "standard",
    "grade", "iso_group", "insert_code", "insert_shape", "clearance_angle", "size_code",
    "corner_radius_mm", "extra_json",
]

# --------------------------------------------------------------------------------------------------
# Классификация разделов
# --------------------------------------------------------------------------------------------------
SUBSECTION_MAP = {
    "пластины для точения": ("insert", "turning_insert"),
    "пластины для фрез": ("insert", "milling_insert"),
    "резьбовые пластины": ("insert", "threading_insert"),
    "отрезные и канавочные пластины": ("insert", "grooving_insert"),
    "пластины для сверл": ("insert", "drill_insert"),
    "свёрла со сменными пластинами": ("drill", "indexable_drill_body"),
    "сверла со сменными пластинами": ("drill", "indexable_drill_body"),
    "твердосплавные свёрла": ("drill", "solid_carbide_drill"),
    "свёрла центровочные твердосплавные": ("drill", "center_drill"),
    "корончатые свёрла": ("drill", "crown_drill"),
    "головки твердосплавные для свёрл": ("drill", "drill_head"),
    "корпус сверла под головку": ("drill", "drill_body"),
    "метчики метрические": ("tap", "machine_tap"),
    "метчики резьба unc/unf": ("tap", "machine_tap"),
    "метчики трубные (g)": ("tap", "pipe_tap"),
    "метчики раскатники": ("tap", "forming_tap"),
    "метчики конические": ("tap", "machine_tap"),
    "метрическая резьба (m)": ("die", "threading_die"),
    "фрезы концевые": ("mill", "end_mill"),
    "фрезы сферические": ("mill", "ball_mill"),
    "фрезы радиусные": ("mill", "radius_mill"),
    "фрезы с винтовой канавкой": ("mill", "end_mill"),
    "фрезы с прямой канавкой": ("mill", "slot_mill"),
    "фрезы трехсторонние с твердосплавными напайными пластинами": ("mill", "slot_mill"),
    "твердосплавные дисковые отрезные фрезы": ("mill", "slot_mill"),
    "фрезы для т-образных пазов с твердосплавными напайными пластинами": ("mill", "slot_mill"),
    "фрезы со сменными пластинами": ("mill", "face_mill"),
    "торцевые насадные фрезы": ("mill", "face_mill"),
    "фрезы концевые ц/х с твердосплавными напайными пластинами": ("mill", "end_mill"),
    "державки для наружного точения": ("holder", "holder_external"),
    "державки для внутреннего точения": ("holder", "holder_internal"),
    "державки для обработки канавок и отрезки": ("holder", "holder_grooving"),
    "державки для обработки внутренних канавок": ("holder", "holder_grooving"),
    "державки резьбовые наружные": ("holder", "holder_threading"),
    "державки резьбовые внутренние": ("holder", "holder_threading"),
    "державки для минирезцов": ("holder", "holder_mini"),
    "минирезцы": ("holder", "mini_tool"),
    "ручные развертки": ("reamer", "hand_reamer"),
    "машинные развертки": ("reamer", "machine_reamer"),
    "зенковки": ("countersink", "countersink"),
    "инструмент для снятия заусенцев": ("countersink", "deburring_blade"),
    "фаскосниматели": ("countersink", "deburring_blade"),
    "пилы твердосплавные": ("mill", "saw_blade"),
    "запасные части для державок и фрез": ("accessory", "spare_part"),
    "винты": ("accessory", "spare_part"),
    "измерительные инструменты": ("accessory", "measuring"),
    "станки": ("accessory", "machine"),
    "ручной и слесарный инструмент": ("accessory", "hand_tool"),
}

# Подразделы оснастки: определяем по типу крепления/принадлежности.
ACCESSORY_HINTS = [
    ("цанг", "collet"), ("патрон", "chuck"), ("сож", "coolant"), ("сопл", "coolant"),
    ("тиск", "machine_vice"), ("кулачк", "machine_jaw"), ("центр", "center"), ("круг", "grinding_wheel"),
    ("соединит", "adapter"), ("держател", "tool_holder"), ("адаптер", "adapter"),
]

NAME_FAMILY_HINTS = [
    (r"пластин", ("insert", "insert")),
    (r"сверл", ("drill", "hss_drill")),
    (r"метчик", ("tap", "machine_tap")),
    (r"плашк", ("die", "threading_die")),
    (r"фрез", ("mill", "end_mill")),
    (r"борфрез", ("mill", "burr")),
    (r"разверт", ("reamer", "machine_reamer")),
    (r"зенков", ("countersink", "countersink")),
    (r"державк|борштанг", ("holder", "holder_external")),
    (r"минирез", ("holder", "mini_tool")),
    (r"цанг", ("accessory", "collet")),
    (r"пил", ("mill", "saw_blade")),
]

UNKNOWN_SECTIONS: List[str] = []

# Тип товара в начале названия: только тогда это запчасть (а не «винтовая фреза»).
_RE_SPARE_NAME = re.compile(
    r"^(?:винт|винты|винта|гайка|гайки|гаек|шайба|шайбы|шайб|пружина|пружины|пружинная|пружинные|ключ|ключи)\b"
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()


SUBSECTION_MAP_NORM = {_norm(k): v for k, v in SUBSECTION_MAP.items()}


def classify(section: str, subsection: str, name: str = "") -> Tuple[str, str]:
    sub = _norm(subsection)
    sec = _norm(section)
    low_name = _norm(name)
    pair: Optional[Tuple[str, str]] = SUBSECTION_MAP_NORM.get(sub)
    if pair is None:
        for key, val in SUBSECTION_MAP_NORM.items():
            if key in sub or (sub and sub in key and len(sub) > 8):
                pair = val
                break
    if pair is None and ("оснастк" in sec or "оснастк" in sub):
        pair = ("accessory", "accessory")
        for hint, cat in ACCESSORY_HINTS:
            if hint in sub:
                pair = ("accessory", cat)
                break
    if pair is None:
        for pattern, val in NAME_FAMILY_HINTS:
            if re.search(pattern, low_name):
                pair = val
                if val[1] == "insert":
                    pair = ("insert", "milling_insert" if "фрез" in low_name else "turning_insert")
                elif val[1] == "hss_drill" and "твердосплав" in low_name:
                    pair = ("drill", "solid_carbide_drill")
                break

    # Крепёж и ключи — запчасть, только когда это тип товара (начало названия), а не слово
    # внутри: «винт. кан.» метчика, «винтовая фреза», «с открытым винтом» остаются инструментом.
    if _RE_SPARE_NAME.match(low_name):
        return "accessory", "spare_part"
    if (pair is None or pair[0] == "accessory") and "державк" in low_name and "сверл" in low_name:
        return "drill", "drill_holder"
    if "лезвие" in low_name or "гратосним" in low_name:
        return "countersink", "deburring_blade"
    if pair is not None:
        return pair

    for section_hint, cat in (("измерительн", "measuring"), ("слесарн", "hand_tool"), ("станк", "machine")):
        if section_hint in sec:
            return "accessory", cat
    key = f"{section} > {subsection}".strip(" >")
    if key not in UNKNOWN_SECTIONS:
        UNKNOWN_SECTIONS.append(key)
    return "other", "other"


# --------------------------------------------------------------------------------------------------
# Разбор атрибутов из названия
# --------------------------------------------------------------------------------------------------
_NUM = r"\d+(?:[.,]\d+)?"
_RE_TRIPLE = re.compile(rf"(?<![\w.])({_NUM})\s*[xх×*]\s*({_NUM})(?:\s*[xх×*]\s*({_NUM}))?(?:\s*[xх×*]\s*({_NUM}))?")
_RE_METRIC = re.compile(r"(?<![A-Za-zА-Яа-я0-9])[MmМм]\s*(\d+(?:[.,]\d+)?)\s*(?:[xXхХ×*]\s*(\d+(?:[.,]\d+)?))?")
_RE_INCH = re.compile(r"(?<![\w.])(\d+/\d+)\s*-\s*(\d+)\s*(UNC|UNF|UNEF|NPT|BSP)?", re.I)
_RE_PIPE = re.compile(r"(?<![A-Za-z0-9])G\s*(\d+(?:[./]\d+)?)\b")
_RE_DIA = re.compile(rf"(?:Ø|⌀|D\s*=|d\s*=|диаметр\s*)\s*({_NUM})", re.I)
_RE_MM = re.compile(rf"(?<![\w.])({_NUM})\s*мм\b", re.I)
_RE_TEETH = [re.compile(r"(?<![\w.])(\d+)\s*F\b"), re.compile(r"[Zz]\s*=\s*(\d+)"), re.compile(rf"({_NUM})\s*зуб")]
_RE_ANGLE = re.compile(rf"({_NUM})\s*°")
_RE_STANDARD = re.compile(r"(ГОСТ\s*[\d.\-]+|DIN\s*\d+|ISO\s*\d+|ANSI\s*[\w.\-]+)", re.I)
_RE_COATING = re.compile(r"\b(TiSiN|TiAlN|AlTiN|AlCrN|TiCN|TiN|DLC|nACo|nano|ZrN|Black|FIRE|PVD|CVD)\b", re.I)
_RE_HRC = re.compile(r"HRC\s*(\d+)", re.I)
_RE_GRADE = re.compile(r"(?<![\w.])([PМMKHNS]\d{2,3}[A-ZА-Я]?|[A-Z]{2,4}\d{2,4}[A-Z]?)(?![\w.])")
_GRADE_HINT = re.compile(r"^(LF\d{4}|LDA|MHN\d+[A-Z]?|PC\d{4}|DP\d+|H\d{2}|K\d{2}|P\d{2}|M\d{2}[A-Z]?|[A-Z]{2}\d{3,4})$", re.I)
_RE_INSERT_CODE = re.compile(r"(?<![\w.])([A-Z]{2,4}[A-Z]?\d{2,4}[A-Z]{0,4})(?![\w.])")
_RE_DIM = re.compile(rf"({_NUM})")


def _f(s: Any) -> Optional[float]:
    if s is None:
        return None
    txt = str(s).strip().replace(",", ".")
    if not txt or txt.lower() in ("nan", "none"):
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _i(s: Any) -> Optional[int]:
    v = _f(s)
    return None if v is None else int(round(v))


def _first(seq: Iterable[Any]) -> Optional[Any]:
    for x in seq:
        return x
    return None


def _fmt_num(s: str) -> str:
    v = float(str(s).replace(",", "."))
    return str(int(v)) if v == int(v) else ("%g" % v)


def _dims(name: str) -> List[float]:
    for m in _RE_TRIPLE.finditer(name):
        vals = [v for v in m.groups() if v]
        if len(vals) >= 2:
            return [float(v.replace(",", ".")) for v in vals]
    return []


def extract_common(name: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    m = _RE_COATING.search(name)
    if m:
        out["coating"] = m.group(1)
    m = _RE_STANDARD.search(name)
    if m:
        out["standard"] = re.sub(r"\s+", " ", m.group(1)).upper()
    m = _RE_HRC.search(name)
    if m:
        out["hrc"] = int(m.group(1))
    grade = None
    for tok in re.findall(r"[A-Za-zА-Яа-я0-9-]+", name):
        up = tok.upper().replace("К", "K")
        if any(ch.isdigit() for ch in up) and _GRADE_HINT.match(up) and not re.fullmatch(r"\d+", up):
            if up.startswith(("LF", "LDA", "MHN", "PC", "DP", "H", "K", "P", "M")) or up in ("VHM",):
                grade = up
                break
    if grade:
        out["grade"] = grade
    low = name.lower()
    if "твердосплав" in low or "vhm" in low:
        out["material"] = "твердый сплав"
    elif "hss-co" in low or "р6м5к5" in low or "p6m5k5" in low:
        out["material"] = "HSS-Co"
    elif "hss-e" in low:
        out["material"] = "HSS-E"
    elif "hss" in low or "р6м5" in low or "p6m5" in low:
        out["material"] = "HSS"
    elif "9хс" in low:
        out["material"] = "9ХС"
    return out


def extract_thread(name: str) -> Dict[str, Any]:
    up = name.upper().replace("М", "M").replace("Х", "X").replace("*", "X")
    out: Dict[str, Any] = {}
    g = _RE_PIPE.search(up)
    if g:
        out["thread"] = f"G{g.group(1)}"
        out["thread_type"] = "pipe"
        return out
    inch = _RE_INCH.search(up)
    if inch and "/" in inch.group(1):
        kind = (inch.group(3) or "UNC").upper()
        out["thread"] = f"{inch.group(1)}-{inch.group(2)}{kind}"
        out["thread_type"] = "inch"
        out["diameter_inch"] = inch.group(1)
        return out
    m = _RE_METRIC.search(up)
    if m:
        d_num = _fmt_num(m.group(1))
        out["thread"] = f"M{d_num}x{_fmt_num(m.group(2))}" if m.group(2) else f"M{d_num}"
        out["thread_type"] = "metric"
        out["diameter_mm"] = float(m.group(1).replace(",", "."))
        if m.group(2):
            out["pitch_mm"] = float(m.group(2).replace(",", "."))
        low = name.lower()
        if "раскат" in low:
            out["tap_kind"] = "forming"
        elif "гаечн" in low:
            out["tap_kind"] = "nut"
        elif "трубн" in low:
            out["tap_kind"] = "pipe"
        elif "коническ" in low:
            out["tap_kind"] = "taper"
        elif "сквозн" in low or "м/р" in low:
            out["tap_kind"] = "through"
    return out


def extract_teeth(name: str) -> Optional[int]:
    for rx in _RE_TEETH:
        m = rx.search(name)
        if m:
            v = _i(m.group(1))
            if v and 0 < v <= 100:
                return v
    return None


def _size_code_from_iso(code: str) -> Optional[str]:
    """CNMG120408 -> 12; APMT1604 -> 16; WCMT06T308 -> 06."""
    m = re.match(r"^[A-Z]{2,4}[A-Z]?(\d{2}|\d{2}T)", code or "")
    if m:
        return m.group(1)[:2]
    return None


def _turning_code_from_name(src: str) -> Dict[str, Any]:
    """CNMG 12 04 08 / CNMG 120408 в начале названия -> код, размер, радиус."""
    up = (src or "").upper().strip()
    m = re.match(r"^([A-Z]{2,4})\s+(\d{2})\s+(\d{2})\s+(\d{2})", up) or \
        re.match(r"^([A-Z]{2,4})\s*(\d{2})(\d{2})(\d{2})", up)
    if not m:
        return {}
    r_str = m.group(4)
    r = int(r_str) / 100.0 if r_str.startswith("00") else int(r_str) / 10.0
    return {"iso_code": m.group(1) + m.group(2) + m.group(3) + m.group(4),
            "insert_shape": m.group(1)[0], "size_code": m.group(2), "corner_radius_mm": r}


def _milling_insert_code(src: str) -> Dict[str, Any]:
    """APMT 160408PDER -> APMT160408; код может быть записан разрядами через пробел."""
    toks = (src or "").upper().split()
    for i, tok in enumerate(toks[:-1]):
        if re.fullmatch(r"[A-Z]{3,5}", tok):
            m = re.match(r"^(\d{2})(\d{2})(\d{2})", toks[i + 1])
            if m:
                return {"iso_code": tok + "".join(m.groups()), "insert_shape": tok[0], "size_code": m.group(1)}
            m = re.match(r"^(\d{2})(\d{2})", toks[i + 1])
            if m:
                return {"iso_code": tok + "".join(m.groups()), "insert_shape": tok[0], "size_code": m.group(1)}
    return {}


def parse_attrs(family: str, category: str, name: str, tech: str, cols: Dict[str, str]) -> Dict[str, Any]:
    """Атрибуты позиции. Колонки [ATT_*] (если есть) главнее разбора названия."""
    src = tech or name
    a: Dict[str, Any] = {}
    a.update(extract_common(src))
    if family == "insert":
        base: Dict[str, Any] = {}
        if category == "turning_insert":
            base = parse_turning(tech) if tech else {}
            if not base.get("iso_code") and name:
                base = parse_turning(name)
        for key in ("iso_code", "insert_shape", "clearance_angle", "size_code", "corner_radius_mm",
                    "chipbreaker", "operation", "hand", "grade", "thickness_code", "tolerance"):
            if base.get(key) not in (None, ""):
                a[key] = base[key]
        if not a.get("iso_code"):
            from src import iso1832
            codes = iso1832.find_codes(tech or name)
            if codes:
                c = codes[0]
                a["iso_code"] = c["code"]
                a.setdefault("insert_shape", c["shape"])
                a.setdefault("size_code", c["size_code"])
                if c.get("corner_r") is not None:
                    a.setdefault("corner_radius_mm", c["corner_r"])
        if not a.get("iso_code"):
            a.update(_turning_code_from_name(tech or name))
        if not a.get("iso_code"):
            a.update(_milling_insert_code(tech or name))
        if cols:
            shape_col = cols.get("ATT_FORMA_PLASTINI", "")
            if shape_col and re.match(r"^[A-Z]", shape_col.upper()):
                a["insert_shape"] = shape_col.upper()[0]
            for key, code in (("size_code", "ATT_RAZMER_US_PLASTINI"), ("corner_radius_mm", "ATT_RADIUS_SCRUGLENIYA")):
                v = _f(cols.get(code))
                if v is not None:
                    a[key] = int(v) if key == "size_code" else v
            mat = cols.get("ATT_OBR_MATERIAL", "")
            if mat:
                m = re.match(r"([PMKNSH])\b", mat.upper())
                if m:
                    a["iso_group"] = m.group(1)
            extra_mat = cols.get("ATT_OBR_MATERIAL_DOPOLNITELNYI", "")
            if extra_mat:
                a["secondary_iso"] = ",".join(sorted(set(re.findall(r"\b[PMKNSH]\b", extra_mat.upper()))))
            op = cols.get("ATT_VID_OBRABOTKI", "").lower()
            if op:
                a["operation_text"] = op
                if "чистов" in op and "полу" not in op:
                    a["operation"] = "finishing"
                elif "получист" in op:
                    a["operation"] = "semi_finishing"
                elif "чернов" in op:
                    a["operation"] = "roughing"
        if category == "milling_insert" and a.get("iso_code"):
            a["size_code"] = a.get("size_code") or _size_code_from_iso(a["iso_code"])
        if category == "threading_insert":
            m = re.search(r"(?<!\d)(\d{2})(ER|IR|EL|IL)\b", src.upper())
            if m:
                a["thread_profile"] = "внутренняя" if "I" in m.group(2) else "наружная"
                a["size_code"] = m.group(1)
            p = re.search(r"(?<!\d)(\d\.\d{1,2})(?!\d)", src)
            if p:
                a["pitch_mm"] = float(p.group(1))
            ang = re.search(r"[ANWG]\s*(55|60)", src.upper())
            if ang:
                a["angle_deg"] = int(ang.group(1))
        if category == "grooving_insert":
            m = re.search(r"(?<!\d)(\d{1,2})GR\s*(\d{2,3})\b", src.upper())
            if m:
                a["width_mm"] = int(m.group(2)) / 100.0
            d = re.search(r"(?<!\d)(\d)(00|10|15|20|25|30|40)\b", src)
            if d:
                a["size_code"] = f"{d.group(1)}{d.group(2)}"
    elif family in ("drill", "reamer", "countersink"):
        d = _RE_DIA.search(src)
        dims = _dims(src)
        if category == "indexable_drill_body":
            m = re.match(r"^[A-Z](\d{2})-(\d)D(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", src)
            if m:
                a["shank_mm"] = float(m.group(1))
                a["ld_ratio"] = int(m.group(2))
                a["diameter_mm"] = float(m.group(3))
                a["length_mm"] = float(m.group(4))
        elif category == "drill_head":
            m = re.search(rf"\b([A-Z]{{2,4}})\s*({_NUM})", src)
            if m:
                a["head_code"] = m.group(1)
                a["diameter_mm"] = float(m.group(2).replace(",", "."))
        elif dims and category == "center_drill":
            a["diameter_mm"] = dims[0]
            if len(dims) >= 3:
                a["cutting_length_mm"], a["shank_mm"] = dims[1], dims[2]
                if len(dims) >= 4:
                    a["length_mm"] = dims[3]
        elif dims and category in ("countersink", "deburring_blade"):
            a["diameter_mm"] = dims[0]
            if len(dims) > 1 and 45 <= dims[1] <= 180:
                a["angle_deg"] = dims[1]
        elif dims:
            a["diameter_mm"] = dims[0]
            if len(dims) == 2:
                a["length_mm"] = dims[1]
            elif len(dims) == 3:
                a["cutting_length_mm"] = dims[1]
                a["length_mm"] = dims[2]
            else:
                a["cutting_length_mm"], a["shank_mm"], a["length_mm"] = dims[1], dims[2], dims[3]
        if a.get("diameter_mm") is None:
            if d:
                a["diameter_mm"] = float(d.group(1).replace(",", "."))
            else:
                mm = _RE_MM.search(src)
                if mm:
                    a["diameter_mm"] = float(mm.group(1).replace(",", "."))
        ang = _RE_ANGLE.search(src)
        if ang and category in ("countersink", "center_drill"):
            a["angle_deg"] = float(ang.group(1).replace(",", "."))
        if ang and "angle_deg" not in a:
            a["angle_deg"] = float(ang.group(1).replace(",", "."))
        if "ld_ratio" not in a:
            ld = re.search(r"(\d{1,2})D(?![A-Za-z0-9])", src)
            if ld and 1 <= int(ld.group(1)) <= 30:
                a["ld_ratio"] = int(ld.group(1))
        low = src.lower()
        if "коническ" in low:
            a["tip"] = "conical"
        if "корончат" in low:
            a["drill_kind"] = "crown"
        if "центровоч" in low:
            a["drill_kind"] = "center"
        if "weldon" in low:
            a["shank"] = "Weldon"
        elif "ц/х" in low:
            a["shank"] = "цилиндрический"
        m = re.search(r"хв\.?\s*(\d+(?:[.,]\d+)?)", low)
        if m:
            a["shank_mm"] = float(m.group(1).replace(",", "."))
        t = extract_thread(src)
        if t.get("thread") and category in ("reamer", "hand_reamer"):
            a.update(t)
    elif family == "mill":
        dims = _dims(src)
        if dims:
            a["diameter_mm"] = dims[0]
            if len(dims) >= 4:
                a["shank_mm"], a["cutting_length_mm"], a["length_mm"] = dims[1], dims[2], dims[3]
            elif len(dims) == 3:
                a["shank_mm"], a["length_mm"] = dims[1], dims[2]
            elif len(dims) == 2:
                a["length_mm"] = dims[1]
        else:
            d = _RE_DIA.search(src)
            if d:
                a["diameter_mm"] = float(d.group(1).replace(",", "."))
            else:
                mm = re.search(rf"^({_NUM})\s*мм\b", src)
                if mm:
                    a["diameter_mm"] = float(mm.group(1).replace(",", "."))
        if category == "face_mill":
            up = src.upper()
            fm = re.search(r"(?<!\d)(\d{2,3})\s*-\s*(\d{1,3})\s*-\s*(\d{1,2})\s*[TТ](?![A-Za-zА-Яа-я])", up)
            if fm:
                a["diameter_mm"] = float(fm.group(1))
                a["bore_mm"] = float(fm.group(2))
                a["teeth"] = int(fm.group(3))
            else:
                fm = re.search(r"C(\d{2})-(\d{2})x(\d{3})-(\d+)[TТ]", up)
                if fm:
                    a["shank_mm"] = float(fm.group(1))
                    a["diameter_mm"] = float(fm.group(2))
                    a["length_mm"] = float(fm.group(3))
                    a["teeth"] = int(fm.group(4))
        z = extract_teeth(src)
        if z:
            a["teeth"] = z
        m = re.search(r"хв\.?\s*(\d+(?:[.,]\d+)?)", src.lower())
        if m:
            a["shank_mm"] = float(m.group(1).replace(",", "."))
        m = re.search(r"\b([A-Z]{2,4}\d{2,4}\*{0,2})\b", src.upper())
        if m and category == "face_mill":
            a["insert_code"] = m.group(1).rstrip("*")
        if category == "ball_mill":
            a["tip"] = "ball"
        elif category == "radius_mill":
            r = re.search(rf"R\s*({_NUM})", src, re.I)
            if r:
                a["radius_mm"] = float(r.group(1).replace(",", "."))
        if category == "thread_mill" or "резьбофрез" in src.lower():
            a.update({k: v for k, v in extract_thread(src).items() if k in ("thread", "pitch_mm", "diameter_mm")})
        if category == "slot_mill" and "дисков" in src.lower() and dims:
            a["diameter_mm"], a["thickness_mm"], a["bore_mm"] = dims[0], dims[-1], (dims[1] if len(dims) > 1 else None)
            a.pop("shank_mm", None)
            a.pop("length_mm", None)
            a.pop("cutting_length_mm", None)
        elif category == "saw_blade":
            z = re.search(r"[Zz]\s*=\s*(\d+)", src)
            if z:
                a["teeth"] = int(z.group(1))
            if dims:
                a["diameter_mm"] = dims[0]
                if len(dims) > 1:
                    a["thickness_mm"] = dims[1]
                if len(dims) > 3:
                    a["bore_mm"] = dims[3]
                a.pop("shank_mm", None)
                a.pop("length_mm", None)
                a.pop("cutting_length_mm", None)
    elif family in ("tap", "die"):
        a.update(extract_thread(src))
        if category == "threading_die":
            a["tool_kind"] = "die"
        else:
            a["tool_kind"] = "tap"
    elif family == "holder":
        code = src.split()[0].upper() if src.strip() else ""
        a["holder_code"] = code
        m = re.match(r"^[A-Z]{1,2}(\d{2})(\d{2})", code)
        if m:
            a["shank_mm"] = float(m.group(1))
            a["insert_size_code"] = m.group(2)[:2]
        m = re.match(r"^([A-Z]{2,3})([1-9]\d)(\d{2})", code)
        if m:
            a.setdefault("diameter_mm", float(m.group(2)))
            a.setdefault("min_bore_mm", float(m.group(3)))
        m = re.match(r"^S(\d{2})([A-Z])-?([A-Z]{3,4})(\d{2})", code)
        if m:
            a["shank_mm"] = float(m.group(1))
            a["insert_size_code"] = m.group(4)
            a["holder_code"] = code
        m = re.search(r"([A-Z]{2,4})(\d{2})$", code)
        if m and "insert_size_code" not in a:
            a["insert_size_code"] = m.group(2)
        dims = _dims(src)
        if dims and "shank_mm" not in a:
            a["shank_mm"] = dims[0]
        if category == "mini_tool":
            m = re.match(r"([A-Z]{3})\s*(\d+)", code)
            if m:
                a["mini_code"] = m.group(1)
    elif family == "accessory":
        if category == "collet":
            m = re.search(r"\bER-?(\d{1,2})\b", src.upper())
            if m:
                a["collet_series"] = f"ER{m.group(1)}"
            m = re.search(rf"({_NUM})\s*[-–]\s*({_NUM})", src)
            if m:
                a["clamp_range"] = f"{m.group(1)}-{m.group(2)}"
        elif category == "spare_part":
            a.update(extract_thread(src))
        elif category == "measuring":
            dims = _dims(src)
            if dims:
                a["size"] = "x".join(str(int(x)) if x == int(x) else str(x) for x in dims)
    return {k: v for k, v in a.items() if v not in (None, "", [])}


# --------------------------------------------------------------------------------------------------
# Разбор раскладок
# --------------------------------------------------------------------------------------------------
def _row_map(headers: Sequence[str], row: Sequence[str]) -> Dict[str, str]:
    idx = header_index(headers)
    out: Dict[str, str] = {}
    for key, i in idx.items():
        if i < len(row):
            val = row[i]
            if val:
                out[key] = val
    return out


def _get(m: Dict[str, str], *keys: str) -> str:
    for k in keys:
        v = m.get(k)
        if v:
            return v
    return ""


def parse_price_layout(sheets: Sequence[Sheet]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Общий прайс: Артикул товара | Наименование | Бренд | Раздел | Подраздел | Цена | Остаток."""
    items: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {"layout": "price", "rows": 0, "sheets": []}
    for sheet in sheets:
        hi = find_header_row(sheet.rows, ["артикул товара"])
        if hi is None:
            continue
        headers = sheet.rows[hi]
        idx = header_index(headers)
        sku_i = idx.get("артикул товара", 0)
        name_i = idx.get("наименование товара", 1)
        brand_i = idx.get("бренд", 2)
        sec_i = 3
        sub_i = 4
        price_i = None
        stock_i = None
        for k, i in idx.items():
            if k.startswith("цена") and price_i is None:
                price_i = i
            if k.startswith("доступное количество"):
                stock_i = i
        price_i = price_i if price_i is not None else 5
        stock_i = stock_i if stock_i is not None else 6
        section = subsection = ""
        for row in sheet.rows[hi + 1:]:
            def cell(i, row=row):
                return row[i] if i is not None and i < len(row) else ""
            sku = cell(sku_i).strip()
            name = cell(name_i).strip()
            if not sku and not name:
                continue
            if not name and not cell(brand_i) and not cell(sec_i):
                continue
            if not re.search(r"[A-Za-zА-Яа-я]", sku) and not re.match(r"^\d+$", sku):
                continue
            if not name:
                continue
            if not cell(brand_i) and not cell(price_i):
                # строка-заголовок раздела: название раздела в колонке артикула
                continue
            s1 = cell(sec_i).strip()
            s2 = cell(sub_i).strip()
            if s1:
                section = s1
            if s2:
                subsection = s2
            brand = cell(brand_i).strip()
            price = _f(cell(price_i))
            stock = _i(cell(stock_i)) or 0
            family, category = classify(section, subsection, name)
            attrs = parse_attrs(family, category, name, "", {})
            items.append({
                "id": sku,
                "sku": sku,
                "name": name,
                "brand": brand,
                "family": family,
                "category": category,
                "section": section,
                "subsection": subsection,
                "stock": stock,
                "price": price or 0.0,
                "currency": "RUB",
                "price_on_request": bool(not price or round(price, 1) == 999.9),
                "active": True,
                "attrs": attrs,
                "_source": sheet.name,
            })
        info["rows"] += len(items)
        info["sheets"].append(sheet.name)
    return items, info


def parse_bitrix_layout(sheets: Sequence[Sheet]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Детальная выгрузка Битрикса: ID элемента + колонки [ATT_*]."""
    items: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {"layout": "bitrix", "rows": 0, "sheets": [], "schema": {}}
    for sheet in sheets:
        hi = find_header_row(sheet.rows, ["ID элемента".lower(), "att_forma_plastini", "TECHNAME".lower()])
        if hi is None:
            continue
        headers = sheet.rows[hi]
        info["schema"][sheet.name] = schema_hash(headers)
        for row in sheet.rows[hi + 1:]:
            cols = _row_map(headers, row)
            elem_id = (cols.get("id элемента") or "").strip()
            if not elem_id.isdigit():
                continue
            name = (cols.get("наименование элемента") or "").strip()
            tech = (cols.get("techname") or "").strip()
            section = (cols.get("название раздела") or "").strip() or "Пластины для точения"
            subsection = section
            family, category = classify(section, subsection, name or tech)
            attrs = parse_attrs(family, category, name, tech, cols)
            price = _f(cols.get("цена \"цена продажи\"")) or _f(cols.get('цена "цена"')) or 0.0
            if str(cols.get("ндс включен в цену?", "")).strip().upper() == "N" and price > 0:
                vat = _f(cols.get("ставка ндс")) or 0.0
                price = round(price * (1 + vat / 100.0), 2)
            por = str(cols.get("att_getprice", "")).strip().lower() in ("да", "y", "yes", "1")
            brand = (cols.get("brand") or "").strip()
            sku = (cols.get("vendorcode_qtool") or cols.get("vendorcode") or tech or name)[:120]
            items.append({
                "id": elem_id,
                "sku": sku,
                "name": name or tech,
                "brand": brand,
                "family": family,
                "category": category,
                "section": section,
                "subsection": subsection,
                "stock": _i(cols.get("доступное количество")) or 0,
                "price": price,
                "currency": (cols.get("валюта для цены \"цена\"") or "RUB").upper()[:3],
                "price_on_request": por or price <= 0 or round(price, 1) == 999.9,
                "active": (cols.get("активность") or "Y").upper() != "N",
                "attrs": attrs,
                "_source": sheet.name,
            })
        info["rows"] += len(items)
        info["sheets"].append(sheet.name)
    return items, info


def detect_and_parse(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    sheets = read_workbook(path)
    if not sheets:
        raise ValueError(f"Пустая книга: {path}")
    head_flat = []
    for sh in sheets:
        for row in sh.rows[:12]:
            head_flat.extend(row)
    low = " | ".join(h.lower() for h in head_flat if h)
    items: List[Dict[str, Any]] = []
    infos = []
    if "id элемента" in low:
        it, inf = parse_bitrix_layout(sheets)
        items.extend(it); infos.append(inf)
    if "артикул товара" in low:
        it, inf = parse_price_layout(sheets)
        items.extend(it); infos.append(inf)
    if not infos:
        raise ValueError(f"Неизвестная раскладка таблицы: {os.path.basename(path)}")
    info = {
        "file": os.path.basename(path),
        "sha256": _sha256_file(path),
        "sheets": [s.name for s in sheets],
        "row_count": len(items),
        "layouts": infos,
    }
    return items, info


# --------------------------------------------------------------------------------------------------
# Сборка, слияние, валидация
# --------------------------------------------------------------------------------------------------
def _norm_sku(s: str) -> str:
    return re.sub(r"[^A-Z0-9А-Я]", "", (s or "").upper())


def _merge_items(primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """secondary (общий прайс с актуальной ценой) дополняет primary (детальная выгрузка с атрибутами)."""
    out: Dict[str, Dict[str, Any]] = {}
    for it in primary:
        out[it["id"]] = it
    for it in secondary:
        cur = out.get(it["id"])
        if not cur:
            out[it["id"]] = it
            continue
        cur["price"] = it["price"] or cur["price"]
        cur["stock"] = max(cur["stock"], it["stock"])
        cur["price_on_request"] = it["price_on_request"]
        cur["active"] = True
        if not cur.get("name"):
            cur["name"] = it["name"]
        if not cur.get("brand"):
            cur["brand"] = it["brand"]
    return list(out.values())


def build_site_catalog(files: Sequence[str], urls: Optional[Dict[str, str]] = None,
                       out_csv: str = SITE_CSV, manifest: str = MANIFEST) -> Dict[str, Any]:
    urls = urls or {}
    UNKNOWN_SECTIONS.clear()
    detailed: List[Dict[str, Any]] = []
    price: List[Dict[str, Any]] = []
    source_infos = []
    for path in files:
        items, info = detect_and_parse(path)
        source_infos.append(info)
        layouts = {lay["layout"] for lay in info["layouts"]}
        for it in items:
            (detailed if "bitrix" in layouts else price).append(it)

    merged = _merge_items(detailed, price)

    prev = _read_manifest(manifest)
    prev_total = int(prev.get("total") or 0)
    total = len(merged)
    warnings = []
    if prev_total and total < prev_total * 0.8:
        raise ValueError(f"Отклонение объёма каталога: было {prev_total}, стало {total} (< 80%). Снимок не подменён.")
    if UNKNOWN_SECTIONS:
        warnings.append("Неизвестные разделы отправлены в карантин: " + "; ".join(UNKNOWN_SECTIONS[:10]))

    by_family: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    rows = []
    for it in merged:
        fam = it["family"]
        by_family[fam] = by_family.get(fam, 0) + 1
        by_category[it["category"]] = by_category.get(it["category"], 0) + 1
        attrs = dict(it.get("attrs") or {})
        extra = {k: v for k, v in attrs.items() if k not in _ATTR_COLUMNS}
        row = {k: "" for k in FIELDS}
        row.update({
            "id": it["id"], "sku": it["sku"], "name": it["name"], "brand": it["brand"],
            "family": fam, "category": it["category"], "section": it["section"], "subsection": it["subsection"],
            "stock": it["stock"], "price": it["price"], "currency": it.get("currency", "RUB"),
            "price_on_request": "1" if it.get("price_on_request") else "0",
            "active": "1" if it.get("active", True) else "0",
            "url": urls.get(str(it["id"])) or f"{QTOOL_BASE}/search/?q={urllib.parse.quote(it['sku'])}",
            "extra_json": json.dumps(extra, ensure_ascii=False) if extra else "",
        })
        for key in _ATTR_COLUMNS:
            if attrs.get(key) not in (None, ""):
                row[key] = attrs[key]
        rows.append(row)

    rows.sort(key=lambda r: (r["family"], r["category"], r["name"]))
    _atomic_write_csv(out_csv, rows)
    rep = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": total,
        "prev_total": prev_total,
        "sources": source_infos,
        "by_family": by_family,
        "by_category": by_category,
        "unknown_sections": UNKNOWN_SECTIONS[:30],
        "warnings": warnings,
    }
    _atomic_write_json(manifest, rep)
    return rep


_ATTR_COLUMNS = [
    "coating", "material", "size", "diameter_mm", "shank_mm", "length_mm", "cutting_length_mm",
    "teeth", "pitch_mm", "thread", "angle_deg", "radius_mm", "width_mm", "standard",
    "grade", "iso_group", "insert_code", "insert_shape", "clearance_angle", "size_code", "corner_radius_mm",
]


def _atomic_write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def _atomic_write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_manifest(path: str = MANIFEST) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------------------------------
# Скачивание
# --------------------------------------------------------------------------------------------------
def _ssl_context() -> ssl.SSLContext:
    """Цепочка qtool.ru (ddos-guard) не всегда есть в системном хранилище Windows.

    certifi используется, если установлен; QTOOL_INSECURE_TLS=1 — крайняя мера для стенда.
    """
    if os.environ.get("QTOOL_INSECURE_TLS") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def http_get(url: str, timeout: int = 90, headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes, Dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, b"", dict(e.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b"", {}


def _url_exists(url: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status == 200:
                return int(resp.headers.get("Content-Length") or 0) > 0
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    code, _, _ = http_get(url, timeout=25, headers={"Range": "bytes=0-0"})
    return code in (200, 206)


def discover_plates_url(days: int = 30) -> Optional[str]:
    """В имени файла дата (03.11.26); каталог /upload/ отдаёт 403, поэтому перебираем свежие даты."""
    env = os.environ.get("QTOOL_PLATES_URL")
    if env:
        return env
    today = time.localtime()
    for back in range(days):
        ts = time.mktime((today.tm_year, today.tm_mon, today.tm_mday - back, 12, 0, 0, 0, 0, -1))
        lt = time.localtime(ts)
        url = PLATES_TEMPLATE.format(date=time.strftime("%d.%m.%y", lt))
        if _url_exists(url):
            return url
    return None


def download_file(url: str, dest: str, prev_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Условный GET: если файл не изменился (ETag/Last-Modified), не скачиваем повторно."""
    headers = {}
    if prev_meta and prev_meta.get("url") == url:
        if prev_meta.get("etag"):
            headers["If-None-Match"] = prev_meta["etag"]
        if prev_meta.get("last_modified"):
            headers["If-Modified-Since"] = prev_meta["last_modified"]
    code, body, resp_headers = http_get(url, headers=headers)
    if code == 304 and os.path.exists(dest):
        return {"url": url, "file": dest, "status": "not_modified", "sha256": prev_meta.get("sha256")}
    if code != 200 or not body:
        raise RuntimeError(f"Не удалось скачать {url}: HTTP {code}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, dest)
    return {
        "url": url, "file": dest, "status": "ok", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
        "etag": resp_headers.get("ETag", ""), "last_modified": resp_headers.get("Last-Modified", ""),
    }


def fetch_site_urls(path: str = URLS_JSON) -> Dict[str, str]:
    """id элемента -> ссылка на карточку из sitemap каталога."""
    code, body, _ = http_get(SITEMAP_CATALOG, timeout=120)
    if code != 200:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    text = body.decode("utf-8", errors="replace")
    urls: Dict[str, str] = {}
    for loc in re.findall(r"<loc>([^<]+)</loc>", text):
        m = re.search(r"/(\d+)/?$", loc)
        if m:
            urls.setdefault(m.group(1), loc)
    if urls:
        _atomic_write_json(path, urls)
    return urls


def refresh(dest_dir: str = UPLOAD_DIR) -> Dict[str, Any]:
    """Скачать свежие таблицы, обновить ссылки и пересобрать каталог."""
    os.makedirs(dest_dir, exist_ok=True)
    prev = _read_manifest()
    prev_sources = {s.get("url"): s for s in (prev.get("sources") or [])}
    downloaded = []
    price_url = next((u for u in PRICE_URLS if _url_exists(u)), PRICE_URLS[0])
    downloaded.append(download_file(price_url, os.path.join(dest_dir, "price.xlsx"), prev_sources.get(price_url)))
    plates_url = discover_plates_url()
    if not plates_url:
        raise RuntimeError("Не найден свежий файл детальной выгрузки пластин (QTOOL_PLATES_URL не задан)")
    downloaded.append(download_file(plates_url, os.path.join(dest_dir, "plates.xlsx"), prev_sources.get(plates_url)))
    urls = fetch_site_urls()
    rep = build_site_catalog([os.path.join(dest_dir, "price.xlsx"), os.path.join(dest_dir, "plates.xlsx")], urls)
    rep["downloads"] = downloaded
    # манифест перезаписывается ещё раз, чтобы сохранить условный GET для следующего запуска
    _atomic_write_json(MANIFEST, rep)
    return rep


def load_site_catalog(path: str = SITE_CSV) -> List[Dict[str, Any]]:
    """Читает снимок каталога. Атрибуты лежат отдельными колонками + extra_json."""
    items: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            attrs = {}
            for key in _ATTR_COLUMNS:
                val = (row.get(key) or "").strip()
                if val:
                    if key in ("teeth", "hrc"):
                        num = _f(val)
                        if num is not None:
                            attrs[key] = int(num)
                    elif key.endswith(("_mm", "_deg")):
                        num = _f(val)
                        if num is not None:
                            attrs[key] = num
                    else:
                        attrs[key] = val
            extra_raw = row.get("extra_json") or ""
            if extra_raw:
                try:
                    attrs.update(json.loads(extra_raw))
                except ValueError:
                    pass
            items.append({
                "id": row.get("id", ""),
                "sku": row.get("sku", ""),
                "name": row.get("name", ""),
                "brand": row.get("brand", ""),
                "family": row.get("family", ""),
                "category": row.get("category", ""),
                "section": row.get("section", ""),
                "subsection": row.get("subsection", ""),
                "stock": _i(row.get("stock")) or 0,
                "price": _f(row.get("price")) or 0.0,
                "currency": row.get("currency") or "RUB",
                "price_on_request": (row.get("price_on_request") or "0") == "1",
                "active": (row.get("active") or "1") != "0",
                "url": row.get("url", ""),
                "attrs": attrs,
            })
    return items


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = refresh()
    print(json.dumps(report, ensure_ascii=False, indent=1))
