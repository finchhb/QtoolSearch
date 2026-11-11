"""
build_catalog.py - Быстрый универсальный парсер прайс-листов и таблиц остатков (.xlsx)
на 100% стандартной библиотеке Python (без необходимости установки pandas/openpyxl):
  1. Rinscom.com: https://www.rinscom.com/downloads/price_sale.xlsx
  2. qtool.ru:    https://qtool.ru/upload/V/smennie_plastini_ISO_tochenie_03.11.26.xlsx

Формирует:
  - Ссылки на страницы магазинов (rinscom_url и qtool_url).
  - Кросс-сопоставление между Rinscom.com и qtool.ru: если пластина есть и там, и там,
    к позиции прикрепляются ДВЕ ссылки (и на Rinscom.com, и на qtool.ru).
  - Кэшированные каталоги data/catalog_rinscom.csv, data/catalog_qtool.csv, data/catalog_both.csv
    для мгновенного переключения источников.
"""
import csv
import os
import re
import ssl
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional, Tuple

RINSCOM_PRICE_URL = "https://www.rinscom.com/downloads/price_sale.xlsx"
QTOOL_PRICE_URL = "https://qtool.ru/upload/V/smennie_plastini_ISO_tochenie_03.11.26.xlsx"

RINSCOM_DEFAULT_XLSX = "data/price_sale.xlsx"
QTOOL_DEFAULT_XLSX = "data/smennie_plastini_ISO_tochenie_03.11.26.xlsx"

CATALOG_RINSCOM_CSV = "data/catalog_rinscom.csv"
CATALOG_QTOOL_CSV = "data/catalog_qtool.csv"
CATALOG_BOTH_CSV = "data/catalog_both.csv"

SECTIONS = {
    "Пластины для точения": "turning_insert",
    "Твердосплавные пластины": "turning_insert",
    "Резьбовые пластины": "thread_insert",
    "Отрезные и канавочные пластины": "groove_insert",
    "Державки токарные": "turning_holder",
    "Державки": "turning_holder",
}

BRANDS = [
    ("Boro Deskar", "Deskar"),
    ("Deskar", "Deskar"),
    ("DESKAR", "Deskar"),
    ("ZZKLT", "ZZKLT"),
    ("ZCC-CT", "ZCC-CT"),
    ("ZCC", "ZCC-CT"),
    ("TOOTOOL", "TOOTOOL"),
    ("Qtool", "Qtool"),
    ("QKIT", "QKIT"),
    ("Sekira", "Sekira"),
    ("STV", "STV"),
    ("Mitsubishi", "Mitsubishi"),
    ("Искар", "Iscar"),
    ("Iscar", "Iscar"),
    ("ISCAR", "Iscar"),
    ("Sandvik", "Sandvik"),
    ("SANDVIK", "Sandvik"),
    ("Sumitomo", "Sumitomo"),
    ("SUMITOMO", "Sumitomo"),
    ("Hadsto", "Hadsto"),
    ("Korloy", "Korloy"),
    ("KORLOY", "Korloy"),
    ("GeeFun", "GeeFun"),
    ("SECO", "Seco"),
    ("Seco", "Seco"),
    ("TaeguTec", "TaeguTec"),
    ("PRAMET", "Pramet"),
    ("TUNGALOY", "Tungaloy"),
    ("KENNAMETAL", "Kennametal"),
    ("Walter", "Walter"),
    ("Palbit", "Palbit"),
    ("Kyocera", "Kyocera"),
    ("WIDIA", "Widia"),
    ("Ceratizit", "Ceratizit"),
    ("ARNO", "Arno"),
    ("OKE", "OKE"),
]

BRAND_NORM_MAP = {k.upper(): v for k, v in BRANDS}

CHIPBREAKER_OPERATIONS = {
    # Чистовые (finishing)
    "HA": "finishing", "HQ": "finishing", "EF": "finishing", "DF": "finishing",
    "PF": "finishing", "UF": "finishing", "WF": "finishing", "KF": "finishing",
    "MF": "finishing", "LP": "finishing", "FH": "finishing", "NF": "finishing",
    "F3P": "finishing", "F3M": "finishing", "AL": "finishing", "LC": "finishing",
    "GF": "finishing", "XF": "finishing", "SF": "finishing", "LF": "finishing",
    "F": "finishing", "SL": "finishing",
    # Получистовые (semi_finishing / medium)
    "PM": "semi_finishing", "UR": "semi_finishing", "CQ": "semi_finishing",
    "MQ": "semi_finishing", "DQ": "semi_finishing", "EM": "semi_finishing",
    "DM": "semi_finishing", "MM": "semi_finishing", "KM": "semi_finishing",
    "MA": "semi_finishing", "MP": "semi_finishing", "MH": "semi_finishing",
    "TF": "semi_finishing", "GN": "semi_finishing", "M3P": "semi_finishing",
    "M3M": "semi_finishing", "TM": "semi_finishing", "UM": "semi_finishing",
    "HM": "semi_finishing", "VM": "semi_finishing", "M": "semi_finishing",
    "U": "semi_finishing", "MT": "semi_finishing",
    # Черновые (roughing)
    "PR": "roughing", "HR": "roughing", "GR": "roughing", "ER": "roughing",
    "DR": "roughing", "GS": "roughing", "MR": "roughing", "KR": "roughing",
    "RP": "roughing", "GH": "roughing", "NR": "roughing", "R3P": "roughing",
    "OR": "roughing", "TH": "roughing", "R-S": "roughing", "R": "roughing",
}


def build_rinscom_url(sku: str, code_1c: str, category: str, iso_code: str, size_code: str, family_code: str) -> str:
    """Формирует точную ссылку на страницу товара или серии пластины в интернет-магазине rinscom.com."""
    cat_slug_map = {
        "turning_insert": "dlya-tocheniya",
        "thread_insert": "rezbovye-plastiny",
        "groove_insert": "otreznye-i-kanavochnye",
    }
    cat_slug = cat_slug_map.get(category, "dlya-tocheniya")

    for cand in (sku, code_1c):
        c_str = str(cand or "").strip()
        if re.match(r"^\d{4,8}$", c_str):
            return f"https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/{cat_slug}/{c_str}/"

    if category == "turning_insert" and iso_code:
        iso_clean = re.sub(r"[^a-z0-9]", "", iso_code.lower())
        if len(iso_clean) >= 6:
            return f"https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/dlya-tocheniya/tags/kod_manufacturer-is-{iso_clean}/"
        elif len(iso_clean) >= 4:
            return f"https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/dlya-tocheniya/tags/marka_plastini-is-{iso_clean[:4]}/"

    if category == "thread_insert":
        if size_code and str(size_code).isdigit():
            return f"https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/rezbovye-plastiny/tags/att_razmer_us_plastini-is-{int(size_code)}/"
        return "https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/rezbovye-plastiny/"

    if category == "groove_insert":
        if family_code:
            fc_clean = re.sub(r"[^a-z0-9]", "", family_code.split("-")[0].lower())
            if fc_clean:
                return f"https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/otreznye-i-kanavochnye/tags/kod_manufacturer-is-{fc_clean}/"
        return "https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/otreznye-i-kanavochnye/"

    return f"https://www.rinscom.com/katalog/plastiny-tverdosplavnye/plastiny-smennye/{cat_slug}/"


def build_qtool_url(elem_id: str, category: str = "turning_insert") -> str:
    """Формирует точную ссылку на карточку пластины в интернет-магазине qtool.ru по ID элемента."""
    eid = re.sub(r"[^\d]", "", str(elem_id or ""))
    if eid:
        return f"https://qtool.ru/plastiny/plastiny-dlya-tocheniya/{eid}/"
    return "https://qtool.ru/plastiny/plastiny-dlya-tocheniya/"


def download_price_file(dest_path: str, url: str, timeout: int = 30) -> Tuple[bool, str]:
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
        },
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            data = resp.read()
            if len(data) < 1000:
                return False, "Загруженный файл слишком мал или пуст."
            with open(dest_path, "wb") as f:
                f.write(data)
        return True, f"Файл успешно скачан с {url} ({len(data) // 1024} КБ)"
    except Exception as e:
        return False, f"Не удалось скачать {url}: {e}"


def download_price_sale(dest_path: str = RINSCOM_DEFAULT_XLSX, url: str = RINSCOM_PRICE_URL, timeout: int = 30) -> Tuple[bool, str]:
    return download_price_file(dest_path=dest_path, url=url, timeout=timeout)


def download_qtool_price(dest_path: str = QTOOL_DEFAULT_XLSX, url: str = QTOOL_PRICE_URL, timeout: int = 35) -> Tuple[bool, str]:
    return download_price_file(dest_path=dest_path, url=url, timeout=timeout)


def load_grades_lookup(grades_csv_path: str = "data/grades.csv") -> Dict[str, Dict[str, str]]:
    lookup = {}
    if not os.path.exists(grades_csv_path):
        return lookup
    with open(grades_csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            g = (row.get("grade") or "").strip().upper()
            if g:
                iso_groups = row.get("iso_groups", "")
                if not iso_groups and any(row.get(k) for k in ("iso_p", "iso_m", "iso_k", "iso_n", "iso_s", "iso_h")):
                    letters = []
                    for letter in "PMKNSH":
                        val = row.get(f"iso_{letter.lower()}", "0")
                        if val and val != "0":
                            letters.append(letter)
                    iso_groups = ",".join(letters)
                lookup[g] = {
                    "iso_groups": iso_groups,
                    "secondary_iso": row.get("secondary_iso", ""),
                    "coating": row.get("coating", ""),
                    "brand": row.get("brand", ""),
                    "note": row.get("note") or row.get("description", ""),
                }
    # Справочник компании (import_docs.py): ISO сплавов из методички Дескар и таблицы Келит — см. apply_docs_iso()
    docs_path = os.path.join(os.path.dirname(grades_csv_path) or ".", "grades_docs.csv")
    if os.path.exists(docs_path) and os.environ.get("GRADES_DOCS_OVERRIDE", "1") != "0":
        with open(docs_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                g = (row.get("grade") or "").strip().upper()
                letters = (row.get("iso_groups") or "").strip()
                if not (g and letters):
                    continue
                scope = (row.get("scope") or "all").strip()
                if scope == "add_only" and g in lookup:
                    continue
                entry = lookup.setdefault(g, {"iso_groups": "", "secondary_iso": "", "coating": "", "brand": row.get("brand", ""), "note": ""})
                entry["docs_letters"], entry["docs_scope"] = letters, scope
    return lookup


def apply_docs_iso(prim: List[str], sec: List[str], grade_info: Dict[str, str]):
    """Справочник компании (методичка Дескар, таблица Келит) только ДОБАВЛЯЕТ группы ISO к тем, что уже есть у сплава.
    Ничего не отбирается: сверка с живой карточкой YBG205 показала, что таблица аналогов неполная (в ней одна строка M20,
    а на сайте и у производителя P10–P30 / M20–M40 / S15–S25). Расхождения (группы каталога, которых нет в справочнике)
    пишет import_docs.py в data/docs_conflicts.csv — их проверяют по карточкам вручную."""
    letters = [x.strip().upper() for x in (grade_info.get("docs_letters") or "").split(",") if x.strip()]
    if not letters:
        return prim, sec
    new_prim = list(prim) + [x for x in letters if x not in prim]
    return new_prim, [x for x in sec if x not in new_prim]


def detect_brand(name: str, grade: Optional[str] = None, grades_lookup: Optional[Dict] = None, explicit_brand: Optional[str] = None) -> str:
    if explicit_brand:
        eb = str(explicit_brand).strip()
        if eb and eb.lower() != "nan":
            return BRAND_NORM_MAP.get(eb.upper(), eb)
    for key, val in BRANDS:
        if re.search(rf"(?<![A-Za-zА-Яа-я0-9]){re.escape(key)}(?![A-Za-zА-Яа-я0-9])", name, re.IGNORECASE):
            return val
    if grade and grades_lookup:
        g_up = grade.strip().upper()
        if g_up in grades_lookup and grades_lookup[g_up].get("brand"):
            return grades_lookup[g_up]["brand"]
    return ""


def head_part(name: str) -> str:
    return re.split(
        r"\s+(?:[Дд]ля\s+точения|[Пп]ластина|[Тт]окарная|[Рр]езьбовая|[Оо]трезная|[Кк]анавочная|[Пп]ри)",
        name,
    )[0].strip()


def parse_turning(name: str) -> dict:
    out = {}
    head = head_part(name)
    head_clean = re.sub(r"^\d[A-Z][-\s]+(?=[A-Z]{4})", "", head.strip())
    toks = head_clean.split()
    if not toks:
        return out
    t0 = toks[0]
    code, _, cb0 = t0.partition("-")
    if not re.match(r"^[A-Z]{4}\d", code):
        if re.match(r"^[A-Z]{4}$", code) and len(toks) >= 2 and re.match(r"^\d{2}[A-Z0-9]{2}\d{2,3}", toks[1]):
            sub_size, _, cb0 = toks[1].partition("-")
            code = code + sub_size
            toks = [code + ("-" + cb0 if cb0 else "")] + toks[2:]
        else:
            return out

    m_hand = re.match(r"^([A-Z]{4}\d{2}[A-Z0-9]{2}\d{2,3})([RL])$", code)
    if m_hand:
        code = m_hand.group(1)
        out["hand"] = m_hand.group(2)

    out["iso_code"] = code
    out["insert_shape"] = code[0]
    out["clearance_angle"] = code[1]
    out["insert_type"] = code[3]
    rest = code[4:]
    m = re.match(r"^(\d{2})([A-Z0-9]{2})(\d{2,3})", rest)
    if m:
        out["size_code"] = m.group(1)
        r_str = m.group(3)
        try:
            if len(r_str) == 3 and r_str.startswith("00"):
                out["corner_radius_mm"] = int(r_str) / 100.0
            else:
                out["corner_radius_mm"] = int(r_str[:2]) / 10.0
        except ValueError:
            out["corner_radius_mm"] = None
    else:
        out["size_code"] = rest[:2]
        out["corner_radius_mm"] = None

    tail = toks[1:]
    grade = None
    chip = cb0 or None
    if tail:
        grade = tail[-1]
        extra = tail[:-1]
        if extra:
            chip = (
                "-".join(([cb0] if cb0 else []) + extra)
                if not cb0
                else cb0 + "-" + "-".join(extra)
            )

    if chip:
        chip = chip.lstrip("-")
    out["chipbreaker"] = chip or ""
    out["grade"] = grade or ""
    out["operation"] = CHIPBREAKER_OPERATIONS.get((chip or "").upper(), "")
    return out


def parse_thread(name: str) -> dict:
    out = {}
    head = head_part(name)
    m = re.match(
        r"^(?:YT)?(\d{2})(E|I)(R|L)?(M|H)?\s*(AG|A|G|N)?\s*([\d.]+)?\s*(ISO|UN|W|TR|NPT|BSPT|ACME)?(?:-S)?\s*(\S+)?",
        head,
    )
    if not m or (not m.group(5) and not m.group(6) and not m.group(7)):
        m2 = re.match(r"^(\d{2})V([EN])R([\d.]+)(ISO|TR)\s*(\S+)?", head)
        if m2:
            out.update(
                size_code=m2.group(1),
                side="external" if m2.group(2) == "E" else "internal",
                pitch_value=float(m2.group(3)),
                thread_profile=m2.group(4),
                grade=m2.group(5) or "",
                family_code="V-thread",
                operation="threading",
            )
            return out
        return out

    size, side, hand, _, prof_mod, pitch, prof, grade = m.groups()
    out["size_code"] = size or ""
    out["side"] = "external" if side == "E" else "internal"
    out["hand"] = hand or "R"
    try:
        out["pitch_value"] = float(pitch) if pitch else None
    except ValueError:
        out["pitch_value"] = None
    out["thread_profile"] = prof or (f"partial_{prof_mod}" if prof_mod else "")
    out["grade"] = grade or ""
    out["family_code"] = "thread"
    out["operation"] = "threading"
    return out


def parse_groove(name: str) -> dict:
    out = {}
    head = head_part(name)
    toks = head.split()
    if not toks:
        return out
    t0 = toks[0]
    out["family_code"] = t0
    m = re.match(r"^MG[MGR]N(\d{3})(?:-([A-Z]))?", t0)
    if m:
        out["groove_width_mm"] = int(m.group(1)) / 100.0
        if m.group(2):
            out["chipbreaker"] = m.group(2)
    else:
        m2 = re.match(r"^TGF\d+[RL](\d{3})", t0)
        if m2:
            out["groove_width_mm"] = int(m2.group(1)) / 100.0
    out["grade"] = toks[-1] if len(toks) > 1 else ""
    out["operation"] = "grooving"
    return out


PARSERS = {
    "turning_insert": parse_turning,
    "thread_insert": parse_thread,
    "groove_insert": parse_groove,
}

_COL_INDEX_CACHE: Dict[str, int] = {}
for _i in range(55):
    _col_s = ("" if _i < 26 else chr(65 + _i // 26 - 1)) + chr(65 + _i % 26)
    _COL_INDEX_CACHE[_col_s] = _i


def _read_xlsx_rows_pure_python(xlsx_path: str, skiprows: int = 0, max_cols: int = 35, max_rows: Optional[int] = None) -> List[List[str]]:
    """
    Высокоскоростной потоковый XML-парсер .xlsx на 100% стандартной библиотеке Python (ET.iterparse).
    Не требует ни pandas, ни openpyxl!
    """
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            with zf.open("xl/sharedStrings.xml") as ss_file:
                cur_texts: List[str] = []
                for event, elem in ET.iterparse(ss_file, events=("end",)):
                    tag = elem.tag
                    if tag.endswith("}t"):
                        if elem.text:
                            cur_texts.append(elem.text)
                    elif tag.endswith("}si"):
                        shared_strings.append("".join(cur_texts))
                        cur_texts = []
                        elem.clear()

        sheet_files = [f for f in zf.namelist() if f.startswith("xl/worksheets/sheet") and f.endswith(".xml")]
        sheet_files.sort()
        if not sheet_files:
            return []

        rows_out: List[List[str]] = []
        ss_len = len(shared_strings)

        with zf.open(sheet_files[0]) as sh_file:
            cur_row: List[str] = []
            cur_r_num = 0
            skip_current = False

            for event, elem in ET.iterparse(sh_file, events=("start", "end")):
                tag = elem.tag
                if event == "start":
                    if tag.endswith("}row"):
                        cur_r_num += 1
                        r_attr = elem.attrib.get("r")
                        if r_attr and r_attr.isdigit():
                            cur_r_num = int(r_attr)
                        skip_current = cur_r_num <= skiprows
                        if not skip_current:
                            cur_row = [""] * max_cols
                else:
                    if not skip_current and tag.endswith("}c"):
                        ref = elem.attrib.get("r", "")
                        col_letters = ""
                        for ch in ref:
                            if ch < "A":
                                break
                            col_letters += ch
                        c_idx = _COL_INDEX_CACHE.get(col_letters, -1)
                        if 0 <= c_idx < max_cols:
                            c_type = elem.attrib.get("t", "")
                            val = ""
                            if c_type == "inlineStr":
                                texts = [ch_el.text or "" for ch_el in elem.iter() if ch_el.tag.endswith("}t")]
                                val = "".join(texts)
                            else:
                                for ch_el in elem:
                                    if ch_el.tag.endswith("}v") and ch_el.text is not None:
                                        if c_type == "s":
                                            s_idx = int(ch_el.text)
                                            if 0 <= s_idx < ss_len:
                                                val = shared_strings[s_idx]
                                        else:
                                            val = ch_el.text
                                        break
                            cur_row[c_idx] = val.strip()
                    elif tag.endswith("}row"):
                        if not skip_current:
                            rows_out.append(cur_row)
                            if max_rows and len(rows_out) >= max_rows:
                                break
                        elem.clear()

        return rows_out


def _to_float(s: object) -> float:
    if s is None:
        return 0.0
    s_str = str(s).strip()
    if not s_str or s_str.lower() == "nan":
        return 0.0
    s_clean = re.sub(r"[^\d.,-]", "", s_str).replace(",", ".")
    try:
        return float(s_clean) if s_clean else 0.0
    except ValueError:
        return 0.0


def _extract_qtool_iso_letters(val: object) -> List[str]:
    if val is None:
        return []
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return []
    found = re.findall(r"\b([PMKNSH])\s*\(", s.upper())
    if not found:
        found = [ch for ch in re.split(r"[,;\s/]+", s.upper()) if ch in ("P", "M", "K", "N", "S", "H")]
    out = []
    for ch in found:
        if ch not in out:
            out.append(ch)
    return out


def _extract_qtool_operations(val: object) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    ops = []
    s_up = s.upper()
    if "L (" in s_up or "F (" in s_up or "ЧИСТОВ" in s_up:
        ops.append("finishing")
    if "M (" in s_up or "ПОЛУЧИСТОВ" in s_up:
        ops.append("semi_finishing")
    if "R (" in s_up or "H (" in s_up or "ЧЕРНОВ" in s_up:
        ops.append("roughing")
    return ",".join(ops)


def _detect_is_qtool_headers(headers: List[str]) -> bool:
    joined = " | ".join(str(h) for h in headers[:15]).lower()
    return ("id элемента" in joined) or ("наименование элемента" in joined) or ("techname" in joined) or ("att_forma_plastini" in joined)


def _parse_qtool_records(records: List[Dict[str, object]], grades_lookup: Dict[str, Dict[str, str]]) -> List[Dict]:
    parsed_rows = []
    for r in records:
        elem_id_raw = r.get("ID элемента")
        if elem_id_raw is None or str(elem_id_raw).strip() in ("", "nan", "None"):
            continue
        elem_id_flt = _to_float(elem_id_raw)
        if elem_id_flt <= 0:
            continue
        elem_id = str(int(round(elem_id_flt)))

        name = str(r.get("Наименование элемента") or "").strip()
        if not name or name.lower() == "nan":
            continue

        tech_raw = r.get("Техническое название [TECHNAME]")
        techname = "" if (tech_raw is None or str(tech_raw).strip().lower() == "nan") else str(tech_raw).strip()

        vc_qtool = str(r.get("Код производителя Qtool [vendorcode_Qtool]") or "").strip()
        vc_main = str(r.get("Код производителя [vendorcode]") or "").strip()
        if vc_qtool.lower() == "nan":
            vc_qtool = ""
        if vc_main.lower() == "nan":
            vc_main = ""

        sku = techname or vc_qtool or vc_main or head_part(name)
        code_ext = vc_main or vc_qtool
        code_1c = f"ID:{elem_id}" + (f" ({code_ext})" if code_ext and code_ext != sku else "")

        sec_name = str(r.get("Название раздела") or "Пластины для точения").strip()
        cat = SECTIONS.get(sec_name, "turning_insert")

        attrs = parse_turning(techname) if techname else {}
        if not attrs.get("iso_code"):
            attrs = parse_turning(name)

        shape_col = str(r.get("Форма пластины [ATT_FORMA_PLASTINI]") or "").strip()
        insert_shape = attrs.get("insert_shape", "")
        if shape_col and shape_col.lower() != "nan" and re.match(r"^[A-Z]", shape_col):
            insert_shape = shape_col[0]

        size_col = r.get("Размер пластины [ATT_RAZMER_US_PLASTINI]")
        size_code = attrs.get("size_code", "")
        if not size_code and size_col is not None and str(size_col).strip() not in ("", "nan"):
            sz_int = int(round(_to_float(size_col)))
            if sz_int > 0:
                size_code = f"{sz_int:02d}"

        rad_col = r.get("Радиус скругления, r (мм) [ATT_RADIUS_SCRUGLENIYA]")
        corner_radius_mm = attrs.get("corner_radius_mm")
        if rad_col is not None and str(rad_col).strip() not in ("", "nan"):
            r_val = _to_float(rad_col)
            if r_val > 0:
                corner_radius_mm = r_val

        grade_raw = (attrs.get("grade") or "").strip()
        grade_clean = re.sub(r"\s+", "", grade_raw).replace("К", "K").upper()
        grade_info = grades_lookup.get(grade_clean, {})

        brand_col = r.get("Бренд [BRAND]")
        brand = detect_brand(name, grade_clean, grades_lookup, explicit_brand=brand_col)

        iso_prim_list = _extract_qtool_iso_letters(r.get("Обрабатываемый материал [ATT_OBR_MATERIAL]"))
        for g_iso in (grade_info.get("iso_groups") or "").split(","):
            g_iso = g_iso.strip().upper()
            if g_iso and g_iso not in iso_prim_list:
                iso_prim_list.append(g_iso)

        iso_sec_list = _extract_qtool_iso_letters(r.get("Дополнительный обрабатываемый материал [ATT_OBR_MATERIAL_DOPOLNITELNYI]"))
        for g_sec in (grade_info.get("secondary_iso") or "").split(","):
            g_sec = g_sec.strip().upper()
            if g_sec and g_sec not in iso_sec_list and g_sec not in iso_prim_list:
                iso_sec_list.append(g_sec)

        iso_prim_list, iso_sec_list = apply_docs_iso(iso_prim_list, iso_sec_list, grade_info)

        operation_qtool = _extract_qtool_operations(r.get("Вид обработки [ATT_VID_OBRABOTKI]"))
        operation = operation_qtool or attrs.get("operation", "")

        stock_val = int(round(_to_float(r.get("Доступное количество"))))
        price_sale = _to_float(r.get('Цена "Цена продажи"'))
        price_base = _to_float(r.get('Цена "Цена"'))
        price_val = round(price_sale if price_sale > 0 else price_base, 2)
        # На сайте цена показывается с НДС. Если в выгрузке «НДС включен в цену? = N» (склады поставщиков), прибавляем ставку:
        # сверено с карточкой 27965 (358,80 → 437,74 ₽; на сайте 437,73 ₽).
        if str(r.get("НДС включен в цену?") or "").strip().upper() == "N" and price_val > 0:
            vat_rate = _to_float(r.get("Ставка НДС")) or 0.0
            price_val = round(price_val * (1 + vat_rate / 100.0), 2)

        # Флаг «Цена по запросу» из выгрузки сайта; 999.9 / 0 в таких строках — заглушка, а не цена
        por_raw = str(r.get("Цена по запросу [ATT_GETPRICE]") or "").strip().lower()
        price_on_request = "1" if (por_raw in ("да", "y", "yes", "1") or price_val <= 0 or round(price_val, 1) == 999.9) else "0"
        active_flag = "Y" if str(r.get("Активность") or "").strip().upper() == "Y" else "N"

        curr_raw = str(r.get('Валюта для цены "Цена"') or "RUB").strip().upper()
        currency = curr_raw if curr_raw and curr_raw != "NAN" else "RUB"

        qtool_url = build_qtool_url(elem_id, cat)

        parsed_rows.append({
            "sku": sku,
            "code_1c": code_1c,
            "category": cat,
            "name": name,
            "brand": brand,
            "stock": stock_val,
            "price": price_val,
            "currency": currency,
            "source_site": "qtool.ru",
            "rinscom_url": "",
            "qtool_url": qtool_url,
            "in_both_stores": "0",
            "head": techname or head_part(name),
            "iso_code": attrs.get("iso_code", ""),
            "insert_shape": insert_shape,
            "clearance_angle": attrs.get("clearance_angle", ""),
            "insert_type": attrs.get("insert_type", ""),
            "size_code": size_code,
            "corner_radius_mm": corner_radius_mm if corner_radius_mm is not None else "",
            "chipbreaker": attrs.get("chipbreaker", ""),
            "operation": operation,
            "hand": attrs.get("hand", ""),
            "side": attrs.get("side", ""),
            "pitch_value": "",
            "thread_profile": "",
            "groove_width_mm": "",
            "family_code": "",
            "grade": grade_clean,
            "iso_group": ",".join(iso_prim_list),
            "secondary_iso": ",".join(iso_sec_list),
            "coating": grade_info.get("coating", ""),
            "price_on_request": price_on_request,
            "active": active_flag,
        })
    return parsed_rows


def load_price_rows(path: str) -> List[Dict]:
    raw_rows = _read_xlsx_rows_pure_python(path, skiprows=6, max_cols=6)
    rows = []
    current_cat = None

    for vals in raw_rows:
        sku, code_1c, name, stock_s, price_s = vals[0], vals[1], vals[2], vals[3], vals[4]
        if sku.lower() in ("артикул", "номенклатура", "sku") or name.lower() in ("наименование", "номенклатура"):
            continue

        is_header = (not code_1c and not name and bool(sku))
        if is_header:
            sec_title = sku.strip()
            matched_sec = None
            for k, v in SECTIONS.items():
                if k.lower() in sec_title.lower():
                    matched_sec = v
                    break
            current_cat = matched_sec or "other"
            continue

        if not name and sku and (stock_s or price_s):
            name = sku

        if not name:
            continue

        cat = current_cat
        if not cat or cat == "other":
            if parse_turning(name).get("iso_code"):
                cat = "turning_insert"
            elif parse_thread(name).get("family_code"):
                cat = "thread_insert"
            elif parse_groove(name).get("groove_width_mm") is not None or re.match(r"^(?:MG[MGR]N|TGF|CTP|8GR)", head_part(name)):
                cat = "groove_insert"
            else:
                cat = current_cat or "turning_insert"

        if cat not in PARSERS and cat != "turning_holder":
            continue

        stock_val = _to_float(stock_s)
        price_val = _to_float(price_s)

        rows.append({
            "sku": sku or head_part(name),
            "code_1c": code_1c,
            "category": cat,
            "name": name,
            "stock": int(round(stock_val)),
            "price": round(price_val, 2),
        })

    return rows


def parse_xlsx_to_rows(price_path: str, grades_lookup: Dict[str, Dict[str, str]]) -> Tuple[List[Dict], str]:
    first_rows = _read_xlsx_rows_pure_python(price_path, skiprows=0, max_cols=32, max_rows=2)
    if first_rows and _detect_is_qtool_headers(first_rows[0]):
        all_rows = _read_xlsx_rows_pure_python(price_path, skiprows=0, max_cols=32)
        headers = [h.strip() for h in all_rows[0]]
        records = []
        for r_vals in all_rows[1:]:
            if not r_vals[0]:
                continue
            rec = {headers[i]: (r_vals[i] if i < len(r_vals) else "") for i in range(len(headers))}
            records.append(rec)
        return _parse_qtool_records(records, grades_lookup), "qtool"

    raw_items = load_price_rows(price_path)
    parsed_rows = []
    for r in raw_items:
        name = r["name"]
        cat = r["category"]
        parser_fn = PARSERS.get(cat)
        attrs = parser_fn(name) if parser_fn else {}

        grade_raw = (attrs.get("grade") or "").strip()
        grade_clean = re.sub(r"\s+", "", grade_raw).replace("К", "K").upper()
        grade_info = grades_lookup.get(grade_clean, {})

        brand = detect_brand(name, grade_clean, grades_lookup)
        _p, _s = apply_docs_iso([x.strip() for x in grade_info.get("iso_groups", "").split(",") if x.strip()],
                                [x.strip() for x in grade_info.get("secondary_iso", "").split(",") if x.strip()], grade_info)
        iso_group = ",".join(_p)
        secondary_iso = ",".join(_s)
        coating = grade_info.get("coating", "")

        iso_code = attrs.get("iso_code", "")
        size_code = attrs.get("size_code", "")
        family_code = attrs.get("family_code", "")
        rinscom_url = build_rinscom_url(r["sku"], r["code_1c"], cat, iso_code, size_code, family_code)

        parsed_rows.append({
            "sku": r["sku"],
            "code_1c": r["code_1c"],
            "category": cat,
            "name": name,
            "brand": brand,
            "stock": r["stock"],
            "price": r["price"],
            "currency": "RUB",
            "source_site": "rinscom.com",
            "rinscom_url": rinscom_url,
            "qtool_url": "",
            "in_both_stores": "0",
            "head": head_part(name),
            "iso_code": iso_code,
            "insert_shape": attrs.get("insert_shape", ""),
            "clearance_angle": attrs.get("clearance_angle", ""),
            "insert_type": attrs.get("insert_type", ""),
            "size_code": size_code,
            "corner_radius_mm": attrs.get("corner_radius_mm") if attrs.get("corner_radius_mm") is not None else "",
            "chipbreaker": attrs.get("chipbreaker", ""),
            "operation": attrs.get("operation", ""),
            "hand": attrs.get("hand", ""),
            "side": attrs.get("side", ""),
            "pitch_value": attrs.get("pitch_value") if attrs.get("pitch_value") is not None else "",
            "thread_profile": attrs.get("thread_profile", ""),
            "groove_width_mm": attrs.get("groove_width_mm") if attrs.get("groove_width_mm") is not None else "",
            "family_code": family_code,
            "grade": grade_clean,
            "iso_group": iso_group,
            "secondary_iso": secondary_iso,
            "coating": coating,
            "price_on_request": "1" if not r["price"] or float(r["price"]) <= 0 else "0",
            "active": "Y",
        })
    return parsed_rows, "rinscom"


def _make_item_match_keys(row: Dict) -> List[str]:
    """Генерирует ключи сопоставления одной и той же пластины между Rinscom.com и qtool.ru."""
    keys = []
    head_norm = re.sub(r"[^A-Z0-9]", "", str(row.get("head") or "").upper())
    if len(head_norm) >= 8:
        keys.append(f"H:{head_norm}")

    iso = str(row.get("iso_code") or "").strip().upper()
    cb = re.sub(r"[^A-Z0-9]", "", str(row.get("chipbreaker") or "").upper())
    gr = re.sub(r"[^A-Z0-9]", "", str(row.get("grade") or "").upper())
    if iso and gr:
        if cb:
            keys.append(f"ICG:{iso}_{cb}_{gr}")
        keys.append(f"IG:{iso}_{gr}")
    return keys


def cross_link_catalogs(rinscom_rows: List[Dict], qtool_rows: List[Dict]) -> None:
    """
    Сопоставляет пластины между таблицами Rinscom.com и qtool.ru.
    Если пластина присутствует и там, и там — заполняет обе ссылки (rinscom_url и qtool_url) и ставит in_both_stores='1'.
    """
    q_lookup: Dict[str, Dict] = {}
    for qr in qtool_rows:
        for k in _make_item_match_keys(qr):
            if k not in q_lookup or int(qr.get("stock") or 0) > int(q_lookup[k].get("stock") or 0):
                q_lookup[k] = qr

    r_lookup: Dict[str, Dict] = {}
    for rr in rinscom_rows:
        for k in _make_item_match_keys(rr):
            if k not in r_lookup or int(rr.get("stock") or 0) > int(r_lookup[k].get("stock") or 0):
                r_lookup[k] = rr

    for rr in rinscom_rows:
        for k in _make_item_match_keys(rr):
            if k in q_lookup:
                rr["qtool_url"] = q_lookup[k]["qtool_url"]
                rr["in_both_stores"] = "1"
                break

    for qr in qtool_rows:
        for k in _make_item_match_keys(qr):
            if k in r_lookup:
                qr["rinscom_url"] = r_lookup[k]["rinscom_url"]
                qr["in_both_stores"] = "1"
                break


CATALOG_FIELDNAMES = [
    "sku", "code_1c", "category", "name", "brand", "stock", "price", "currency", "source_site",
    "rinscom_url", "qtool_url", "in_both_stores",
    "head", "iso_code", "insert_shape", "clearance_angle", "insert_type",
    "size_code", "corner_radius_mm", "chipbreaker", "operation",
    "hand", "side", "pitch_value", "thread_profile", "groove_width_mm",
    "family_code", "grade", "iso_group", "secondary_iso", "coating",
    "price_on_request", "active"
]


def save_catalog_rows(parsed_rows: List[Dict], out_path: str = "data/catalog.csv") -> Dict:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(parsed_rows)

    stats = {
        "total": len(parsed_rows),
        "turning_insert": sum(1 for x in parsed_rows if x["category"] == "turning_insert"),
        "thread_insert": sum(1 for x in parsed_rows if x["category"] == "thread_insert"),
        "groove_insert": sum(1 for x in parsed_rows if x["category"] == "groove_insert"),
        "in_stock": sum(1 for x in parsed_rows if int(x.get("stock") or 0) > 0),
        "in_both_stores": sum(1 for x in parsed_rows if str(x.get("in_both_stores")) == "1"),
    }
    return stats


def load_cached_csv_rows(csv_path: str) -> List[Dict]:
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_catalog(
    price_path: str = RINSCOM_DEFAULT_XLSX,
    out_path: str = "data/catalog.csv",
    grades_path: str = "data/grades.csv",
) -> Dict:
    grades_lookup = load_grades_lookup(grades_path)
    parsed_rows, fmt = parse_xlsx_to_rows(price_path, grades_lookup)

    if fmt == "rinscom" and os.path.exists(QTOOL_DEFAULT_XLSX):
        q_rows = load_cached_csv_rows(CATALOG_QTOOL_CSV)
        if not q_rows:
            q_rows, _ = parse_xlsx_to_rows(QTOOL_DEFAULT_XLSX, grades_lookup)
        cross_link_catalogs(parsed_rows, q_rows)
        save_catalog_rows(parsed_rows, CATALOG_RINSCOM_CSV)
        save_catalog_rows(q_rows, CATALOG_QTOOL_CSV)
        save_catalog_rows(parsed_rows + q_rows, CATALOG_BOTH_CSV)
    elif fmt == "qtool" and os.path.exists(RINSCOM_DEFAULT_XLSX):
        r_rows = load_cached_csv_rows(CATALOG_RINSCOM_CSV)
        if not r_rows:
            r_rows, _ = parse_xlsx_to_rows(RINSCOM_DEFAULT_XLSX, grades_lookup)
        cross_link_catalogs(r_rows, parsed_rows)
        save_catalog_rows(parsed_rows, CATALOG_QTOOL_CSV)
        save_catalog_rows(r_rows, CATALOG_RINSCOM_CSV)
        save_catalog_rows(r_rows + parsed_rows, CATALOG_BOTH_CSV)

    stats = save_catalog_rows(parsed_rows, out_path)
    stats["detected_format"] = fmt
    print(f"Сохранено {stats['total']} позиций (формат: {fmt}, в обоих магазинах: {stats['in_both_stores']}) -> {out_path}")
    return stats


def build_combined_catalog(paths: List[str], out_path: str = "data/catalog.csv", grades_path: str = "data/grades.csv") -> Dict:
    grades_lookup = load_grades_lookup(grades_path)
    r_rows = load_cached_csv_rows(CATALOG_RINSCOM_CSV)
    if not r_rows and os.path.exists(RINSCOM_DEFAULT_XLSX):
        r_rows, _ = parse_xlsx_to_rows(RINSCOM_DEFAULT_XLSX, grades_lookup)
    q_rows = load_cached_csv_rows(CATALOG_QTOOL_CSV)
    if not q_rows and os.path.exists(QTOOL_DEFAULT_XLSX):
        q_rows, _ = parse_xlsx_to_rows(QTOOL_DEFAULT_XLSX, grades_lookup)

    if r_rows and q_rows:
        cross_link_catalogs(r_rows, q_rows)
        save_catalog_rows(r_rows, CATALOG_RINSCOM_CSV)
        save_catalog_rows(q_rows, CATALOG_QTOOL_CSV)

    all_rows = r_rows + q_rows
    save_catalog_rows(all_rows, CATALOG_BOTH_CSV)
    stats = save_catalog_rows(all_rows, out_path)
    stats["detected_format"] = "combined"
    return stats


if __name__ == "__main__":
    p_in = sys.argv[1] if len(sys.argv) > 1 else RINSCOM_DEFAULT_XLSX
    p_out = sys.argv[2] if len(sys.argv) > 2 else "data/catalog.csv"
    if not os.path.exists(p_in):
        print(f"Файл {p_in} не найден локально, пробуем скачать с {RINSCOM_PRICE_URL}...")
        ok, msg = download_price_sale(p_in)
        print(msg)
    if os.path.exists(p_in):
        build_catalog(p_in, p_out)


# Алиас для обратной совместимости с src/engine.py
build_qtool_catalog = build_catalog
