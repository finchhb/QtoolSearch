"""
src/materials_mapping.py - Сопоставление сталей, сплавов и условий резания с ISO группами и геометрией пластин
"""
import csv
import os
import re
from typing import Optional

# Основы слов (stems) для русского языка и точные марки по ГОСТ / AISI
STEM_TO_ISO = [
    # ISO P - Стали
    ("ст3", "P"), ("ст20", "P"), ("ст45", "P"), ("40х", "P"), ("40хн", "P"),
    ("30хгса", "P"), ("09г2с", "P"), ("65г", "P"), ("у8", "P"), ("у10", "P"),
    ("aisi 1045", "P"), ("aisi 4140", "P"), ("42crmo4", "P"), ("c45", "P"),
    ("углеродист", "P"), ("конструкционн", "P"), ("стал", "P"),

    # ISO M - Нержавеющие стали
    ("12х18н10т", "M"), ("08х18н10", "M"), ("08х18н10т", "M"), ("10х17н13м2т", "M"),
    ("20х13", "M"), ("40х13", "M"), ("95х18", "M"),
    ("aisi 304", "M"), ("304", "M"), ("aisi 316", "M"), ("316", "M"), ("316l", "M"),
    ("aisi 321", "M"), ("321", "M"), ("дуплекс", "M"), ("duplex", "M"),
    ("нержав", "M"), ("коррозион", "M"),

    # ISO K - Чугуны
    ("сч15", "K"), ("сч20", "K"), ("сч25", "K"), ("сч30", "K"), ("сч", "K"),
    ("вч40", "K"), ("вч45", "K"), ("вч50", "K"), ("вч60", "K"), ("вч", "K"),
    ("кч30", "K"), ("кч", "K"), ("gg25", "K"), ("ggg40", "K"),
    ("чугун", "K"),

    # ISO N - Цветные металлы и сплавы
    ("д16т", "N"), ("д16", "N"), ("амг6", "N"), ("амг5", "N"), ("амг2", "N"), ("амг", "N"),
    ("в95", "N"), ("ак7", "N"), ("ак12", "N"), ("дюрал", "N"), ("алюмин", "N"),
    ("браж", "N"), ("бронз", "N"), ("латун", "N"), ("лс59", "N"),
    ("медн", "N"), ("медь", "N"), ("капролон", "N"), ("фторопласт", "N"),

    # ISO S - Жаропрочные сплавы и титан
    ("вт1-0", "S"), ("вт6", "S"), ("вт14", "S"), ("вт20", "S"), ("титан", "S"),
    ("инконел", "S"), ("inconel", "S"), ("хн77тюр", "S"), ("хн60вт", "S"),
    ("хн78т", "S"), ("хастеллой", "S"), ("hastelloy", "S"), ("жаропроч", "S"),

    # ISO H - Закаленные стали > 45-65 HRC
    ("шх15", "H"), ("хвг", "H"), ("9хс", "H"), ("х12мф", "H"),
    ("закален", "H"), ("термообраб", "H")
]

BRAND_SYNONYMS = {
    "сандвик": "Sandvik", "sandvik": "Sandvik", "коромант": "Sandvik", "coromant": "Sandvik",
    "корлой": "Korloy", "korloy": "Korloy",
    "искар": "Iscar", "iscar": "Iscar",
    "дескар": "Deskar", "deskar": "Deskar",
    "мицубиси": "Mitsubishi", "mitsubishi": "Mitsubishi", "митсубиси": "Mitsubishi",
    "вальтер": "Walter", "walter": "Walter",
    "зцц": "ZCC-CT", "zcc": "ZCC-CT", "zcc-ct": "ZCC-CT", "zcc ct": "ZCC-CT",
    "секо": "Seco", "seco": "Seco",
    "кенеметал": "Kennametal", "кеннаметал": "Kennametal", "kennametal": "Kennametal",
    "киосера": "Kyocera", "киоцера": "Kyocera", "kyocera": "Kyocera",
    "тунгалой": "Tungaloy", "tungaloy": "Tungaloy",
    "таегутек": "TaeguTec", "taegutec": "TaeguTec",
    "прамет": "Pramet", "pramet": "Pramet",
    "сумитомо": "Sumitomo", "sumitomo": "Sumitomo",
    "тутул": "TOOTOOL", "tootool": "TOOTOOL",
    "кьюкит": "QKIT", "qkit": "QKIT",
    "кьютул": "Qtool", "qtool": "Qtool",
    "ззклт": "ZZKLT", "zzklt": "ZZKLT",
    "секира": "Sekira", "sekira": "Sekira",
    "хадсто": "Hadsto", "hadsto": "Hadsto",
    "оке": "OKE", "oke": "OKE",
}

CLEARANCE_ANGLE_DESCRIPTIONS = {
    "N": "N (0° — негативная двухсторонняя пластина без заднего угла)",
    "C": "C (7° — позитивная односторонняя пластина с задним углом 7°)",
    "P": "P (11° — позитивная односторонняя пластина с задним углом 11°)",
    "B": "B (5° — позитивная односторонняя пластина с задним углом 5°)",
    "D": "D (15° — позитивная пластина с задним углом 15°)",
    "E": "E (20° — позитивная пластина с задним углом 20°)",
    "F": "F (25° — позитивная пластина с задним углом 25°)",
    "G": "G (30° — позитивная пластина с задним углом 30°)",
    "O": "O (нестандартный задний угол)",
}


# --- Определение группы ISO по обрабатываемому материалу -------------------------------------------
# Принцип: берём ВСЕ совпадения и выбираем самое длинное (специфичное). Поэтому «нержавеющей стали»
# даёт M («нержав» длиннее «стал»), а не P, как было раньше (первым срабатывало слово «стал»).
# Свои правила добавляй в data/materials.csv (колонки: pattern, iso, note; pattern — регулярное выражение).
_B = r"(?<![a-zа-яё0-9])"      # граница слева
_E = r"(?![a-zа-яё0-9])"       # граница справа

_BUILTIN_MATERIAL_RULES = [
    # --- S: титан, жаропрочные никелевые и кобальтовые сплавы
    (r"титан[а-я]*", "S"), (r"ti-?6al-?4v", "S"), (r"grade\s?5\b", "S"), (_B + r"вт\d{1,2}(?:-\d)?[а-я]?" + _E, "S"), (_B + r"пт-?\d[а-я]?" + _E, "S"),
    (r"l?nconel", "S"), (r"инконел", "S"), (r"нихром", "S"), (_B + r"х(?:20н80|15н60|20н80т)" + _E, "S"), (r"inconel", "S"), (r"хастеллой", "S"), (r"hastelloy", "S"), (r"монель", "S"),
    (r"monel", "S"), (r"нимоник", "S"), (r"nimonic", "S"), (r"waspaloy", "S"), (r"стеллит", "S"),
    (r"stellite", "S"), (r"жаропроч[а-я]*", "S"), (r"жаростойк[а-я]*", "S"),
    (_B + r"хн\d{2}[а-я]*" + _E, "S"), (_B + r"э[ип]\d{2,4}[а-я]*" + _E, "S"),
    # --- H: закалённые стали и белые чугуны
    (r"закален[а-я]*", "H"), (r"закалк", "H"), (r"цементирован", "H"), (r"азотирован", "H"),
    (r"нихард", "H"),  (r"hardox\s?\d*", "H"), (_B + r"xar\s?\d+" + _E, "H"), (_B + r"ar\s?(?:400|450|500|550|600)" + _E, "H"), (r"белый чугун", "H"),
    # --- M: нержавеющие стали
    (r"нерж[а-я]*", "M"), (r"коррозион[а-я]*", "M"), (r"кислотостойк", "M"), (r"дуплекс", "M"), (r"duplex", "M"),
    (r"stainless", "M"), (r"аустенит", "M"), (r"мартенситн", "M"),
    # ГОСТ: 08Х18Н10Т, 12Х18Н10Т, 20Х13, 40Х13, 12Х17, 15Х25Т, 03Х17Н14М3, 95Х18, 14Х17Н2 ...
    (_B + r"\d{1,2}х(?:13|17|18|25|28)[а-я0-9]*" + _E, "M"),
    (r"(?:aisi|sus|ss|din)\s*-?\s*(?:30[0-9]|31[0-9]|32[0-9]|347|40[0-9]|41[0-9]|42[0-9]|43[0-9]|904)l?" + _E, "M"),
    (_B + r"1\.4[0-9]{3}" + _E, "M"), (r"uns\s?s32205|uns\s?s32750", "M"),
    # --- K: чугуны
    (r"чугун[а-я]*", "K"), (r"cast iron", "K"), (_B + r"(?:сч|вч|кч|чн|чх)\s?-?\d{1,2}" + _E, "K"),
    (_B + r"ggg?\s?-?\d{2}" + _E, "K"),
    # --- N: цветные металлы и неметаллы
    (r"алюмин[а-я]*", "N"), (r"дюрал", "N"), (_B + r"д16[а-я]*" + _E, "N"), (_B + r"амг\d?" + _E, "N"),
    (_B + r"а[кд]\d{1,2}" + _E, "N"), (_B + r"в95" + _E, "N"), (r"латун[а-я]*", "N"), (_B + r"лс?\d{2}" + _E, "N"),
    (r"бронз[а-я]*", "N"), (_B + r"бр[а-я]{0,3}\d+[-а-я0-9]*" + _E, "N"), (r"силумин", "N"), (_B + r"ал\d{1,2}" + _E, "N"), (_B + r"цам\d?-?\d*" + _E, "N"), (r"медн[а-я]*", "N"), (r"медь", "N"), (r"магни", "N"),
    (r"цинк", "N"), (r"капролон", "N"), (r"фторопласт", "N"), (r"полиамид", "N"), (r"пластик", "N"),
    (r"текстолит", "N"), (r"графит", "N"), (r"композит", "N"), (r"carbon fib", "N"),
    # --- P: конструкционные и легированные стали (самые общие основы — самые короткие совпадения)
    (_B + r"(?:40х|40хн|30хгса|38х2мюа|09г2с|65г|у8|у10|ст\s?\d{1,2}|сталь\s?\d{2})" + _E, "P"),
    (r"углеродист", "P"), (r"конструкционн", "P"), (r"легированн", "P"), (r"инструментальн", "P"),
    (r"aisi\s?(?:1045|4140)", "P"), (r"42crmo4", "P"), (_B + r"c45" + _E, "P"),
    (r"стал", "P"),
]

_MATERIALS_FILES = [os.path.join("data", "materials_iso.csv"), os.path.join("data", "materials.csv")]  # справочник компании, затем правки технолога
_MATERIALS_CSV = _MATERIALS_FILES[-1]
_compiled_rules = None
_LATIN2CYR = str.maketrans("abcehkmoptxy", "авсенкмортху")  # латинские двойники -> кириллица (20X13 набрали латиницей)


def _load_rules():
    """Встроенные правила + data/materials_iso.csv (импорт справочника: import_docs.py) + data/materials.csv (ручные правки).
    Побеждает самое длинное совпадение. Колонка note в csv — примечание, которое покажется в ответе."""
    global _compiled_rules
    rules = [(pat, iso, "", False) for pat, iso in _BUILTIN_MATERIAL_RULES]
    for path in _MATERIALS_FILES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    pat = (row.get("pattern") or "").strip().lower()
                    iso = (row.get("iso") or "").strip().upper()
                    note = (row.get("note") or "").strip()
                    if pat and not pat.startswith("#") and iso in ("P", "M", "K", "N", "S", "H"):
                        rules.append((pat, iso, "" if note.startswith("методичка:") else note, True))
        except Exception:
            pass
    compiled = []
    for pat, iso, note, cyr in rules:
        try:
            compiled.append((re.compile(pat), iso, note, cyr))
        except re.error:
            continue
    _compiled_rules = compiled


def reload_material_rules():
    _load_rules()


def detect_material(text: str):
    """(группа ISO, примечание) по тексту запроса: явное «ISO M», твёрдость HRC>=45, иначе самое длинное совпадение по таблице."""
    lower = text.lower().replace("ё", "е")
    m = re.search(r"\biso\s*([pmknsh])\b", lower)
    if m:
        return m.group(1).upper(), ""
    hrc = re.search(r"(\d{2})\s*(?:hrc|хрц|hrс)", lower)
    if hrc and int(hrc.group(1)) >= 45:
        return "H", ""
    if _compiled_rules is None:
        _load_rules()
    cyr_text = lower.translate(_LATIN2CYR)
    best_len, best_iso, best_note = 0, "", ""
    for rx, iso, note, use_cyr in _compiled_rules:
        for mt in rx.finditer(cyr_text if use_cyr else lower):
            if len(mt.group(0)) > best_len:
                best_len, best_iso, best_note = len(mt.group(0)), iso, note
    return best_iso, best_note


def detect_iso_group(text: str) -> str:
    return detect_material(text)[0]


def detect_material_note(text: str) -> str:
    return detect_material(text)[1]


_MARK_RE = re.compile(r"(?<![а-яa-z0-9])\d{1,3}[а-я][а-я0-9-]{2,}", re.I)


def find_unknown_marks(text: str):
    """Марки в стиле ГОСТ (начинаются с цифр, затем кириллица: 03Н17К10В10МТ-ВД), когда материал не определён."""
    return _MARK_RE.findall(text.lower().replace("ё", "е"))


_OP_SEMI = ["получистов", "полу-чистов", "полу чистов", "универсальн", "средн", "полуфиниш"]
_OP_FINISH = ["чистов", "чистой", "начисто", "по чистому", "финиш", "доводк", "зеркал", "глянц", "малый съем", "малый припуск",
              "высокая чистота", "высокой чистот", "шероховатост", "точность поверхност", " ra ", " rz "]
_OP_ROUGH = ["чернов", "чернух", "по черн", "по-черн", "обдир", "обдув", "удар", "корк", "окалин", "прерывист", "тяжел", "тяжёл",
             "большой съем", "большой припуск", "снять припуск", "снять большой", "неровный припуск", "неравномерный припуск",
             "съем металла", "большая глубина"]


def detect_explicit_operation(text: str) -> str:
    """Вид обработки, ТОЛЬКО если он явно назван в запросе (иначе пустая строка).
    «получистовая» проверяется раньше «чистовой» (раньше она из-за подстроки «чистов» ошибочно давала finishing);
    если названы и черновая, и чистовая — это универсальная (semi_finishing)."""
    lower = " " + text.lower().replace("ё", "е") + " "
    if any(w in lower for w in _OP_SEMI):
        return "semi_finishing"
    rough = any(w in lower for w in _OP_ROUGH)
    finish = any(w in lower for w in _OP_FINISH)
    if rough and finish:
        return "semi_finishing"
    if finish:
        return "finishing"
    if rough:
        return "roughing"
    return ""


def detect_application_type(text: str) -> str:
    """Определение характера обработки (с fallback на medium для обратной совместимости)"""
    explicit = detect_explicit_operation(text)
    if explicit == "semi_finishing":
        return "medium"
    return explicit or "medium"


def detect_insert_shape(text: str) -> str:
    """Форма пластины: код ISO или русские слова (ромб/треугольник/квадрат/тригон/...)."""
    from src import iso1832
    return iso1832.detect_shape(text)[0]


def detect_clearance_angle(text: str) -> str:
    """Задний угол: из кода ISO или явного указания (с границами чисел, без ложных '0°' внутри '80°')."""
    from src import iso1832
    return iso1832.detect_clearance(text)


def detect_size_code(text: str) -> str:
    """Код размера: из кода ISO, 'размер 16', 'треугольник 16', '1204', 'N мм' (длина кромки по ГОСТ)."""
    from src import iso1832
    shape = iso1832.detect_shape(text)[0]
    return iso1832.detect_size(text, shape).get("size_code") or ""


def detect_corner_radius(text: str) -> Optional[float]:
    """Радиус вершины: из кода ISO, 'радиус 0,8', 'r0.8', 'R08'."""
    from src import iso1832
    return iso1832.detect_radius(text)
