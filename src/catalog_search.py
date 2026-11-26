"""
src/catalog_search.py - детерминированный поиск по каталогу всех групп qtool.ru (без LLM).

Слои:
1. Нормализация запроса: регистр, омоглифы (кириллица/латиница), неверная раскладка,
   разделители 25x25 / 25х25 / 25×25, десятичная запятая.
2. Разбор намерения: группа товара, код, диаметр, резьба, зубья, хвостовик, покрытие,
   материал, стандарт, радиус, ширина, угол.
3. Подбор: лесенка «точный код -> компактный код -> префикс -> атрибуты -> текст»,
   жёсткие и мягкие фильтры, явная лесенка ослаблений, ближайшие диаметры.
4. Ранжирование: уровень совпадения, наличие, цена, бренд, число совпавших атрибутов.
"""
import math
import os
import re
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src import rates
from src.code_normalize import cyrillic_code_letters, homoglyph_latin, layout_to_latin
from src.iso5608 import parse_holder_code
from src.materials_mapping import detect_iso_group as _detect_iso_group_mapping
from src.site_catalog import _RE_DIA, _RE_MM, SITE_CSV, _dims, extract_common, extract_teeth, extract_thread

# --------------------------------------------------------------------------------------------------
# Нормализация
# --------------------------------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-zа-я0-9]+(?:[.,/][a-zа-я0-9]+)*")
_COMPACT_RE = re.compile(r"[^a-z0-9а-я]")

# Материал обработки -> группа ISO (порядок важен: «жаропрочная сталь» — это S, «12Х18Н10Т» — M)
_MATERIAL_ISO = [
    (r"титан|жаропроч|инконель|inconel|хастеллой|нимоник", "S"),
    (r"нержав|12х18|08х18|10х17|14х17|20х13|40х13|aisi\s?3\d\d|aisi\s?4\d\d", "M"),
    (r"чугун|вч\d|сч\d|кч\d", "K"),
    (r"алюмин|дюрал|латун|бронз|мед[ьи]|цинк", "N"),
    (r"закал|цемент|hrc\s?\d|твердост", "H"),
    (r"стал[ьи]|конструкцион|углеродист|40х|45х|20х|30х|18хгт|40хн", "P"),
]
_OP_RX = [(r"получистов", "semi_finishing"), (r"чистов", "finishing"), (r"чернов", "roughing")]


def material_iso(text: str) -> Optional[str]:
    low = (text or "").lower().replace("ё", "е")
    for pattern, iso in _MATERIAL_ISO:
        if re.search(pattern, low):
            return iso
    # Fallback: CSV-based rules from materials_mapping (handles grades like 11Х11Н2В2МФ -> M)
    iso = _detect_iso_group_mapping(text)
    return iso or None


def operation_from_text(text: str) -> Optional[str]:
    low = (text or "").lower().replace("ё", "е")
    for pattern, op in _OP_RX:
        if re.search(pattern, low):
            return op
    return None


def compact(s: str) -> str:
    return _COMPACT_RE.sub("", (s or "").lower())


def fmt_num(value: Any) -> str:
    """Число для показа: 8.5 -> «8,5», 90.0 -> «90»."""
    if isinstance(value, float):
        return f"{value:g}".replace(".", ",")
    return str(value)


def query_variants(q: str, include_layout: bool = True) -> List[str]:
    """Варианты написания кода: как есть, омоглифы, неверная раскладка, кириллица по буквам кода.

    include_layout=False исключает вариант неверной раскладки (layout_to_latin),
    чтобы русские слова без цифр не склеивались в ложные коды (B2).
    """
    base = (q or "").lower().replace("ё", "е")
    out = [base, homoglyph_latin(base), cyrillic_code_letters(base)]
    if include_layout:
        out.append(layout_to_latin(base))
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def tokenize(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower().replace("ё", "е"))


def _fix_digit_letters(s: str) -> str:
    s = re.sub(r"(?<=\d)[OОQ](?=\d)", "0", s)
    s = re.sub(r"(?<=\d)[lI|](?=\d)", "1", s)
    s = re.sub(r"(?<=\d)B(?=\d)", "8", s)
    # B в конце цифровой последовательности (CNMG12040B -> CNMG120408),
    # но не после полного 6-значного кода (CNMG120408B — B это стружколом)
    return re.sub(r"(?<!\d)(\d{4,5})B$", r"\g<1>8", s)


_HOLDER_PREFIXES = {
    "PCLN", "MCLN", "PWLN", "MWLN", "PTGN", "MTGN", "PDJN", "MDJN", "MVJN", "PVJN",
    "PSSN", "MSSN", "SCLC", "SDJC", "STGC", "SVJB", "SVJC", "SDUC",
}
_INSERT_SHAPES = set("ABCDEHKLMOPRSTVW")
# задний угол — вторая буква кода пластины (CNMG, DCGT); отсекает «SK40», «BT40», «HSK63»
_ISO_CLEARANCE = set("ABCDEFGNP")

# Разговорные синонимы: в каталоге пишется одно, покупатель спрашивает другое.
_WORD_ALIASES = {"барпулер": "барпуллер"}

# Форма пластины словами (ISO 1832): покупатель говорит «ромб», в коде — буква C.
PLATE_SHAPE_WORDS = [
    (r"ромб", "C"),
    (r"квадрат", "S"),
    (r"треугольн", "T"),
    (r"круг|округл|раунд", "R"),
    (r"пятиугольн", "P"),
    (r"шестиугольн", "H"),
    (r"параллелограмм", "A"),
    (r"восьмиугольн", "O"),
]
PLATE_SHAPE_TITLES = {
    "C": "ромб", "S": "квадрат", "T": "треугольник", "R": "круг",
    "P": "пятиугольник", "H": "шестиугольник", "A": "параллелограмм", "O": "восьмиугольник",
}

# Хвостовик оснастки: «BT50-SLN25-100» — конус, диаметр инструмента, длина.
_TAPER_RE = re.compile(r"(?<![A-Z0-9])(HSK|BT|SK|NT|DIN)[\s-]?(\d{2})(?!\d)")


def accessory_mount(name: str) -> Dict[str, Any]:
    """Конус и размеры патрона/оправки из названия: «BT50-SLN25-100» -> taper, d, l."""
    up = (name or "").upper()
    m = _TAPER_RE.search(up)
    if not m:
        return {}
    out: Dict[str, Any] = {"taper": m.group(1) + m.group(2)}
    nums = re.findall(r"\d{2,3}", up[m.end():m.end() + 16])
    if len(nums) >= 2:
        out["d"] = int(nums[0])
        out["l"] = int(nums[1])
    return out


def slot_mm_from_name(name: str) -> Optional[int]:
    """«… паз 14мм …» -> 14: паз стола, под который берут прижимы."""
    m = re.search(r"паз\.?\s*(\d{1,2})(?!\d)", str(name or ""), re.I)
    return int(m.group(1)) if m else None


def gauge_diameter(name: str) -> Optional[float]:
    """«4124-5 калибр-пробка гладкий 5.0 Н7» -> 5.0: номинал гладкого калибра."""
    m = re.search(r"гладк\w*\s*(\d+(?:[.,]\d+)?)", str(name or ""), re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def chuck_capacity(name: str) -> Optional[int]:
    """«ПСС-16 В16» -> 16: верхний диаметр зажима серии самозажимного патрона."""
    m = re.search(r"(?<![A-ZА-Я0-9])[A-ZА-Я]{2,5}-(\d{1,2})(?!\d)", str(name or "").upper())
    return int(m.group(1)) if m else None

# Порядок брендов в выдаче: сначала свои, внутри бренда — больше остатка выше.
BRAND_PRIORITY = ("ZZKLT", "DESKAR", "OLICNC", "ZEGYO")
_BRAND_RANK = {b.lower(): i for i, b in enumerate(BRAND_PRIORITY)}


def _apply_aliases(text: str) -> str:
    out = text or ""
    for src, dst in _WORD_ALIASES.items():
        out = re.sub(rf"(?<![a-zа-яё]){src}", dst, out, flags=re.I)
    return out

# частые префиксы пластин: нужны, чтобы понимать «под APMT» без размера
_COMMON_INSERT_PREFIXES = {
    "CNMG", "DNMG", "VNMG", "WNMG", "TNMG", "SNMG", "KNMX", "KNUX",
    "CCMT", "DCMT", "VCMT", "TCMT", "SCMT", "CCGT", "DCGT", "VCGT", "TCGT",
    "APMT", "APKT", "APHT", "SEKT", "SEKR", "SPKN", "SPMT", "XDLT",
    "RPMT", "RDMW", "RDMT", "LNMU", "LNMT", "SDMT", "EPNW", "WNMU",
    "MGMN", "ZQMX", "16ER", "16IR", "22ER", "22IR",
}


def insert_prefix_from_word(raw: str, known: Iterable[str] = ()) -> Optional[str]:
    """«РПМТ», «APMT», «СТМН» -> латинский префикс пластины (или None).

    Перебираем транслитерацию, транслитерацию после омоглифов и сами омоглифы:
    «Р» транслитерируется в R, а как омоглиф — в P, и угадывать заранее нельзя.
    """
    cands: List[str] = []
    for w in (cyrillic_code_letters(raw), cyrillic_code_letters(homoglyph_latin(raw)), homoglyph_latin(raw)):
        w = w.upper()
        if w not in cands:
            cands.append(w)
    for w in cands:
        if re.fullmatch(r"[A-Z]{2,5}", w) and w[0] in _INSERT_SHAPES and (w in known or w in _COMMON_INSERT_PREFIXES):
            return w
    for w in cands:
        if re.fullmatch(r"[A-Z]{2,5}", w) and w[0] in _INSERT_SHAPES:
            return w
    return None


def _extract_insert_code(src: str) -> Optional[str]:
    """Извлечь код пластины из уже нормализованной строки (все токены верхний регистр).

    Возвращает первый подходящий код, не проверяя префикс против каталога —
    проверку префикса выполняет вызывающий (insert_code_from_text).
    """
    toks = re.findall(r"[A-Z0-9]+", _fix_digit_letters(src))
    for i, tok in enumerate(toks):
        if re.fullmatch(r"[A-Z]{2,5}\d{4,6}[A-Z]{0,4}", tok):
            # MTJNR2525 пишется как 5 букв + 4 цифры, но это код державки, а не пластины.
            if tok[0] in _INSERT_SHAPES and not parse_holder_code(tok):
                return tok
            continue
        # «CNMG120408PM4325»: длинный склеенный токен код+марка/стружколом —
        # отрезаем известный префикс + 4-6 цифр, остаток — марка (не часть кода).
        m = re.match(r"^([A-Z]{2,5})(\d{4,6})([A-Z0-9]+)$", tok)
        if m and m.group(1)[0] in _INSERT_SHAPES and not parse_holder_code(tok):
            pref, digits = m.group(1), m.group(2)
            code = pref + digits
            if not parse_holder_code(code):
                return code
        if re.fullmatch(r"[A-Z]{2,5}", tok):
            if tok[0] not in _INSERT_SHAPES or tok[:4] in _HOLDER_PREFIXES:
                continue  # не пластина (оснастка или транслитерированное слово)
            digits = ""
            j = i + 1
            while j < len(toks) and re.fullmatch(r"\d{1,6}", toks[j]) and len(digits) < 6:
                if len(digits) + len(toks[j]) > 6:
                    break  # «CNMG 1204 4325»: 4325 — марка, а не продолжение кода
                digits += toks[j]
                j += 1
            if 4 <= len(digits) <= 6:
                code = tok + digits
                if not parse_holder_code(code):
                    return code
    return None


def insert_code_from_text(text: str, known: Iterable[str] = ()) -> Optional[str]:
    """CNMG 12 04 08 / CNMG120408 -> CNMG120408. Хвост из букв (стружколом) не приклеиваем.

    Пробуем варианты нормализации в порядке приоритета:
    омоглифы → неверная раскладка → как есть → побуквенная транслитерация.
    Принимаем первый вариант, чей префикс есть в индексе кодов каталога (B1, B2).
    Если ни один вариант не дал известный префикс — возвращаем первого кандидата
    как fallback, чтобы _canonical_insert_code мог исправить опечатку префикса.
    """
    known_set = set(known) | _COMMON_INSERT_PREFIXES
    text = (text or "").lower().replace("ё", "е")
    # порядок: омоглифы (СТМН → CTMN) → неверная раскладка (стьп → CNMG)
    # → как есть → побуквенная транслитерация (для полностью кириллических кодов: РПМТ → RPMT)
    variants = [homoglyph_latin(text), layout_to_latin(text), text, cyrillic_code_letters(text)]
    seen, ordered = set(), []
    for v in variants:
        v = v.upper()
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    fallback = None
    for src in ordered:
        code = _extract_insert_code(src)
        if code is None:
            continue
        if fallback is None:
            fallback = code
        # Принимаем только коды, чей 4-буквенный префикс есть в каталоге (B1).
        # Неизвестные префиксы (например CTMN из стьп120408 через транслит)
        # сохраняем как fallback для канонической коррекции.
        if code[:4] in known_set:
            return code
    # B2: fallback возвращаем только если префикс похож на известный (Дамерау <= 2),
    # иначе ложные коды из омоглифов державок (TK2525 из зсдтк2525м12) уводят в insert.
    if fallback:
        pref = fallback[:4]
        for known_pref in known_set:
            if known_pref[0] == pref[0] and damerau(pref, known_pref, 2) <= 2:
                return fallback
    return None


def holder_code_from_text(text: str) -> Optional[str]:
    """PCLNR 2525 M12 / SNR0006K06-A12 -> компактный код с сохранением дефиса.

    Кодом считаем только структурно полную оснастку ISO 5608: короткие серии
    («SBHA32») — держатели осевого инструмента, а не державки. Берём только токены,
    которые целиком состоят из латиницы (гомоглифы допускаются): «державка» после
    транслитерации иначе приклеивалась бы к коду.
    """
    toks = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", text or "")
    for i, tok in enumerate(toks):
        letters = homoglyph_latin(tok)
        if any(ch.isalpha() and not ("A" <= ch.upper() <= "Z") for ch in letters):
            continue
        cand = letters.upper()
        if parse_holder_code(cand):
            return cand
        if re.fullmatch(r"[A-Z]{1,6}", cand):
            digits = ""
            j = i + 1
            while j < len(toks) and len(digits) < 8:
                nxt = homoglyph_latin(toks[j]).upper()
                if re.fullmatch(r"\d{1,4}|[A-Z]\d{1,3}|\d{2,5}[A-Z]\d{1,3}", nxt):
                    digits += nxt
                    j += 1
                else:
                    break
            if digits and parse_holder_code(cand + digits):
                return cand + digits
    return None


def damerau(a: str, b: str, max_dist: int = 1) -> int:
    """Расстояние Дамерау-Левенштейна с ранним выходом (строки короткие)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    prev2: List[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        best = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            best = min(best, cur[j])
        if best > max_dist:
            return max_dist + 1
        prev2, prev = prev, cur
    return prev[lb]


# --------------------------------------------------------------------------------------------------
# Намерение запроса
# --------------------------------------------------------------------------------------------------
FAMILY_KEYWORDS = [
    ("insert", r"пластин|insert|cnmg|wnmg|tcmt|tcgt|ccmt|ccgt|dcmt|vcgt|apmt|apkt|wcmt|spmg|sekt|lnmu|16er|16ir|22er|22ir|mgmn|mrgn|8gr|6gr|3gr|zqmx"),
    ("drill", r"сверл|сверло|drill|коронк|центровк"),
    ("mill", r"фрез|mill|борфрез"),
    ("tap", r"метчик|\btap\b|раскатник"),
    ("die", r"плашк|\bdies?\b"),
    ("reamer", r"разверт"),
    ("countersink", r"зенков|зенкер|фаскосним|гратосним"),
    ("holder", r"державк|борштанг|holder|резец|резц|минирез|оправк|расточн"),
    ("accessory", r"цанг|патрон|винт|гайк|ключ|сож|тиск|кулачк|адаптер|переходник|втулк|держател|барпул"),
    ("measuring", r"штанген|микрометр|нутромер|линейк|угломер|индикатор|рулетк"),
    ("saw", r"пил[аы]|пильн|дисков.*пил"),
]

CATEGORY_HINTS = {
    "drill": [
        ("center_drill", r"центровоч|центровк"),
        ("crown_drill", r"корончат"),
        ("drill_head", r"(?<!под )головк"),
        ("indexable_drill_body", r"корпусн|сменн.*пластин|под пластину|под головк|сверл\w*[^,.]*пластин"),
        ("solid_carbide_drill", r"твердосплав|vhm"),
        ("hss_drill", r"hss|р6м5|p6m5|к/х"),
    ],
    "mill": [
        ("ball_mill", r"сферич|шарова|ball"),
        ("radius_mill", r"радиусн|с радиусом"),
        ("thread_mill", r"резьбофрез"),
        ("face_mill", r"торцев|насадн|со сменными пластин|корпусн"),
        ("slot_mill", r"дисков|пазов|т-образн|отрезн"),
        ("burr", r"борфрез"),
        ("end_mill", r"концев|end"),
        ("roughing", r"кукуруза|чернов"),
        ("dovetail", r"ласточкин|dovetail"),
    ],
    "tap": [
        ("forming_tap", r"раскатн"),
        ("pipe_tap", r"трубн|\bG\d"),
        ("machine_tap", r"машинн|метрич|сквозн|гаечн"),
    ],
    "holder": [
        ("holder_internal", r"расточн|борштанг|внутренн"),
        ("holder_grooving", r"канавочн|канавк|отрезн"),
        ("holder_threading", r"резьбов"),
        ("holder_external", r"наружн|проходн|подрезн"),
    ],
    "accessory": [
        ("tool_holder", r"осев[а-яё]*\s+инструмент|токарн[а-яё]*\s+блок"),
        # «кулачки», «комплект кулачков», но не «3-х кулачковый патрон» — это сам патрон
        ("machine_jaw", r"кулачк(?:а|и|ов|ам|ами|ах|у|ом)\b"),
        # «цанга ER32», но не «цанговый патрон» — это патрон под цангу
        ("collet", r"цанг(?:а|и|у|ой|ам|ами|ах)\b"),
        ("machine_vice", r"тиск(?:и|ов|ам|ами|ах|)\b"),
    ],
}

CATEGORY_TITLES = {
    "holder_internal": "расточная",
    "holder_external": "наружная",
    "holder_grooving": "канавочная",
    "holder_threading": "резьбовая",
    "tool_holder": "держатель осевого инструмента",
    "machine_jaw": "кулачки",
    "collet": "цанги",
    "machine_vice": "тиски",
}


class Query:
    def __init__(
        self,
        text: str,
        insert_prefixes: Optional[set] = None,
        code_index: Optional[Dict[Tuple[str, str], List[int]]] = None,
    ):
        self.text = (text or "").strip()
        self.low = _apply_aliases(self.text.lower().replace("ё", "е"))
        self.variants = query_variants(self.text)
        self.compact = compact(self.text)
        self.family: Optional[str] = None
        self.category_hints: List[str] = []
        self.attrs: Dict[str, Any] = {}
        self.code: Optional[str] = None
        self.insert_code: Optional[str] = None
        self.holder_code: Optional[str] = None
        self.thread: Optional[str] = None
        self.brand: Optional[str] = None
        self.free_tokens: List[str] = []
        self.compat_insert: Optional[str] = None
        self.compat_prefix: Optional[str] = None
        self.compat_shape: Optional[str] = None
        self.compat_clearance: Optional[str] = None
        self.compat_hole: Optional[str] = None
        self.compat_size: Optional[str] = None
        self.compat_hand: Optional[str] = None
        self.compat_requested = False
        self.holder_compat: Optional[Dict[str, Any]] = None
        self.holder_compat_code: Optional[str] = None
        self.holder_compat_requested = False
        self.shank_round = False
        self._insert_prefixes = insert_prefixes or set()
        self._code_index = code_index
        self._parse()

    def _parse(self) -> None:
        low = self.low
        # «державка 2525 под CNMG1204», «фреза 120 под APMT» — код после «под» задаёт
        # совместимую пластину, а группа определяется по основному слову запроса.
        code_text = self.text
        under = self._parse_compat_insert()
        if under:
            code_text = (self.text[:under[0]] + " " + self.text[under[1]:]).strip()
            # «под dcmt пластину»: хвост фразы не должен уводить запрос в группу пластин
            code_text = _RE_PLATE_WORD.sub(" ", code_text).strip()
        elif _RE_COMPAT_PHRASE.search(code_text):
            # «фреза под пластину» без кода: фраза не должна уводить запрос в группу пластин
            code_text = _RE_COMPAT_PHRASE.sub(" ", code_text).strip()
        if under or _RE_COMPAT_PHRASE.search(self.text):
            self.compat_requested = True
        low = _apply_aliases(code_text.lower().replace("ё", "е"))
        # «сверлильный патрон», «набор прижимов» — это само изделие оснастки:
        # слово «сверлильный» не должно уводить запрос в группу свёрл.
        if re.search(r"\bпатрон|\bприжим", low):
            self.family = "accessory"
        elif re.search(r"калибр|инсайз|insize", low):
            # «калибр-пробка 5 H7», «6282-2002 инсайз»: измерительный инструмент — оснастка
            self.family = "accessory"
            self.category_hints.append("measuring")
        else:
            for fam, pattern in FAMILY_KEYWORDS:
                if re.search(pattern, low):
                    self.family = fam
                    break
        # «сверло с квадратной пластиной» — корпус сверла под пластину, а не пластина:
        # в группу пластин уводит только пластина, названная раньше сверла
        if self.family == "insert" and re.search(r"сверл", low):
            i_drill = low.find("сверл")
            i_plate = low.find("пластин")
            if i_plate < 0 or i_drill < i_plate:
                self.family = "drill"
        for cat, pattern in CATEGORY_HINTS.get(self.family or "", []):
            if re.search(pattern, low):
                self.category_hints.append(cat)
        if self.family == "mill" and re.search(r"шпоночн", low):
            # шпоночная фреза — двухзубая концевая: отсекаем сферические, резьбо- и ласточкины хвосты
            self.attrs["flutes2"] = True
            if "end_mill" not in self.category_hints:
                self.category_hints.append("end_mill")

        # «пластина. Ромб. Размер 09. Радиус 02» — пластина описана словами, без кода
        if self.family in ("insert", "holder"):
            self._parse_plate_spec(low)

        m = re.search(r"(?<![A-Za-z0-9])SBHA\)?\s*(\d{2})(?:\s*[-–]\s*|\s+)(\d{2})(?:\s*[-–]\s*(\d{2,3}))?",
                      self.text, re.I)
        if m:
            # «SBHA12-20»: держатель осевого инструмента — 12 хвостовик, 20 хвост инструмента
            self.family = "accessory"
            if "tool_holder" not in self.category_hints:
                self.category_hints.append("tool_holder")
            self.attrs["shank_mm"] = float(m.group(1))
            self.attrs["clamp_mm"] = float(m.group(2))
            if m.group(3):
                self.attrs["length_mm"] = float(m.group(3))
        elif re.search(r"(?<![A-Za-z0-9])SBHA(?![A-Za-z])", self.text, re.I):
            # «SBHA32» / «SBHA» без второго числа — серия держателей осевого инструмента
            self.family = "accessory"
            if "tool_holder" not in self.category_hints:
                self.category_hints.append("tool_holder")
            one = re.search(r"(?<![A-Za-z0-9])SBHA\)?\s*(\d{2})(?!\d)", self.text, re.I)
            if one:
                self.attrs["shank_mm"] = float(one.group(1))

        # «кулачки к11-400»: серия патрона и его размер; в каталоге «К11-400 кулачки …»
        if self.family == "accessory" and "machine_jaw" in self.category_hints:
            jm = re.search(r"(?<![A-Za-zА-Яа-яЁё0-9])([A-Za-zА-Яа-яЁё])(\d{2})\s*[-–]\s*(\d{2,3})(?!\d)",
                           low)
            if jm:
                self.attrs["jaw_series"] = homoglyph_latin(jm.group(1)).upper() + jm.group(2)
                self.attrs["jaw_size"] = int(jm.group(3))

        if self.family == "accessory":
            if "measuring" in self.category_hints:
                # «6282-2002 инсайз»: артикул вида 0000-000 идёт в название позиции
                cm = re.search(r"(?<![\d-])(\d{4}-\d{2,4})(?![\d-])", low)
                if cm:
                    self.attrs["measure_code"] = cm.group(1)
                # «калибр-пробка 5 H7»: квалитет H7 пишется и кириллицей (Н7)
                tol = re.search(r"(?<![a-zа-я0-9])([hн])\s*(\d{1,2})(?![\d.])", low)
                if tol:
                    self.attrs["tolerance"] = "H" + tol.group(2)
            # «сверлильный самозажимной патрон»: кулачки сходятся сами, это отдельный тип
            if re.search(r"самозажимн", low):
                self.attrs["self_tightening"] = True
                # «1-16мм» — диапазон зажима: у ПСС-16 верхний предел 16
                cr = re.search(r"(?<![\d-])(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(?:мм)?", low)
                if cr:
                    self.attrs["chuck_max_mm"] = int(cr.group(2))
            # «втулка переходная морзе2 на морзе 1» = переход 2/1: в каталоге «2/1 с лапкой … втулка»
            mr = re.search(r"морзе\s*(\d{1,2})\s*на\s*морзе\s*(\d{1,2})", low)
            if not mr:
                mr = re.search(r"(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])", low)
            if mr and "втулк" in low:
                self.attrs["morse_from"] = int(mr.group(1))
                self.attrs["morse_to"] = int(mr.group(2))
                if re.search(r"\bс\s+лапк", low):
                    self.attrs["with_tang"] = True
            if "барпуллер" in low:
                self.attrs["bar_puller"] = True
                # «барпулер 2525»: 25×25 — квадратный хвост, в каталоге «S25 … квадр.хв.»
                sq = re.search(r"(?<!\d)(\d{2})(\d{2})(?!\d)", low)
                if sq and sq.group(1) == sq.group(2):
                    self.attrs["bar_shank_mm"] = int(sq.group(1))
            # «патрон бт50 под велдон 25 длинной 100»: конус, хвостовик, диаметр и длина
            tm = re.search(r"(?<![a-zа-я0-9])(hsk|bt|бт|sk|nt|din)[\s-]?(\d{2})(?!\d)", low)
            if tm:
                self.attrs["taper"] = {"бт": "BT", "bt": "BT", "hsk": "HSK",
                                       "sk": "SK", "nt": "NT", "din": "DIN"}[tm.group(1)] + tm.group(2)
            if re.search(r"велдон|weldon", low):
                self.attrs["weldon"] = True
                # «под велдон 25», «weldon 20»: диаметр хвоста обычно идёт сразу за словом
                dm = (re.search(r"(?:велдон|weldon)\D{0,12}?(\d{1,2}(?:[.,]\d+)?)(?!\d)", low)
                      or re.search(r"(?<!\d)(\d{1,2}(?:[.,]\d+)?)\s*(?:мм\s*)?(?:велдон|weldon)", low))
                if dm:
                    val = float(dm.group(1).replace(",", "."))
                    self.attrs["tool_d_mm"] = int(val) if val == int(val) else val
            lm = re.search(r"(?:длин[а-яё]*|длиной)[\s:.—-]*(\d{2,3})(?!\d)", low)
            if lm:
                self.attrs["tool_l_mm"] = int(lm.group(1))
            vm = re.search(r"(?<![a-z])vdi\s*(\d{1,2})(?!\d)", low)
            if vm:
                self.attrs["chuck_system"] = "VDI" + vm.group(1)
            bm = re.search(r"(?<![a-z0-9])b\s?(\d{2})(?!\d)", low)
            if bm and "патрон" in low:
                self.attrs["chuck_taper"] = "B" + bm.group(1)
            if re.search(r"\bприжим", low):
                self.attrs["clamp_set"] = True
                sm = (re.search(r"(?<!\d)(\d{1,2})\s*(?:мм\s*)?паз", low)
                      or re.search(r"паз\.?\s*(\d{1,2})(?!\d)", low))
                if sm:
                    self.attrs["slot_mm"] = int(sm.group(1))

        # Обратный подбор: «пластина под державку MCLNR2525M12» — какие пластины в неё ставятся.
        # Код после слова «державка» — это код державки, а не пластины.
        rev_holder = None
        if self.family == "insert":
            hm = _RE_HOLDER_MENTION.search(self.text)
            if hm:
                rev_holder = holder_code_from_text(self.text[hm.end():])
                info = holder_insert_compat(rev_holder) if rev_holder else None
                if rev_holder and info and info.get("size"):
                    self.holder_compat_requested = True
                    self.holder_code = rev_holder
                    self.holder_compat = info
                    self.holder_compat_code = rev_holder

        # коды: пробелы в записи кода не значимы (CNMG 12 04 08 = CNMG120408)
        if self.family in (None, "insert"):
            # после «под <пластина>» код уже ушёл в совместимость: группа по нему не определяется
            for v in (query_variants(code_text) if under else self.variants):
                code = insert_code_from_text(v, self._insert_prefixes)
                if code and not compact(rev_holder or "").startswith(compact(code)):
                    self.insert_code = code
                    self.family = "insert"
                    break
        if not self.insert_code and self.family in (None, "insert"):
            # «DCGT 11», «DCGT09», «DCGT 11T302»: префикс и двузначный размер без полного хвоста —
            # обычная короткая запись пластины. Вторая буква — задний угол, поэтому «SK40» и
            # «HSK63» сюда не попадают.
            for v in (query_variants(code_text) if under else self.variants):
                m = re.search(r"(?<![A-Za-z0-9])([A-Z]{2,5})\s?(\d{2})([A-Z]\d{2,4})?(?![A-Za-z0-9])",
                              v.upper())
                if not m:
                    continue
                pref = m.group(1)
                if (pref[0] not in _INSERT_SHAPES or pref[1] not in _ISO_CLEARANCE
                        or pref in _HOLDER_PREFIXES or parse_holder_code(pref + m.group(2))):
                    continue
                if pref not in _COMMON_INSERT_PREFIXES and pref not in self._insert_prefixes:
                    continue
                self.insert_code = pref + m.group(2)
                self.attrs["insert_prefix"] = pref
                self.attrs["size_code"] = m.group(2)
                if m.group(3):
                    self.attrs["iso_tail"] = m.group(3)
                self.family = "insert"
                break
        if self.family in (None, "holder"):
            # все варианты нормализации: омоглифы → как есть → неверная раскладка → транслит.
            # holder_code_from_text отсекает русские слова без цифр, поэтому ложные коды не появится (B2).
            # B2: буква M (класс длины держателя) на русской раскладке — клавиша м, которую
            # layout_to_latin переводит в v. Пробуем вернуть M, иначе державки в русской
            # раскладке не найдутся (в каталоге коды с M, не с V).
            variants = list(query_variants(code_text, include_layout=bool(re.search(r"\d", code_text))))
            lv = layout_to_latin(code_text)
            if any(ch in lv for ch in "vV"):
                variants.append(lv.replace("v", "m").replace("V", "M"))
            found = None
            for v in variants:
                code = holder_code_from_text(v)
                if code:
                    if found is None:
                        found = code
                    # предпочитаем код, который реально есть в каталоге держателей
                    want = compact(code)
                    if self._code_index is not None and ("holder", want) in self._code_index:
                        found = code
                        break
            if found:
                self.holder_code = found
                if self.family is None:
                    self.family = "holder"

        # «пластина под державку» без кода: подбирать не под что, просим код державки.
        if self.family == "insert" and not self.insert_code and _RE_HOLDER_MENTION.search(self.text):
            self.holder_compat_requested = True

        if self.family == "insert":
            up = self.text.upper().replace("Ё", "Е")
            for g in re.finditer(r"(?<![\w.])(\d{4}|[A-Z]{1,3}\d{3,4})(?![\w.])", up):
                # «CNMG 1204 4325»: 1204 — часть кода пластины, марка — следующее число
                if self.insert_code and g.group(1) in self.insert_code:
                    continue
                if not self.holder_compat_requested:
                    grade_raw = g.group(1)
                    # «CNMG120408PM4325»: марка склеена с кодом — убираем буквенный префикс (PM4325 -> 4325)
                    grade_clean = re.sub(r"^[A-Z]+", "", grade_raw)
                    self.attrs["grade"] = grade_clean or grade_raw
                break
            if "grade" not in self.attrs and self.insert_code:
                # «CNMG120408PM4325»: марка склеена с кодом — извлечь хвост после кода
                if up.startswith(self.insert_code):
                    tail = up[len(self.insert_code):]
                    m = re.match(r"^[A-Z]{1,3}(\d{3,4})$", tail)
                    if m and not self.holder_compat_requested:
                        self.attrs["grade"] = m.group(1)
                # «DCGT 11T302 FL K10»: короткая марка вида K10
                g2 = re.search(r"(?<![\w.])([A-Z]{1,2}\d{2})(?![\w.])", up)
                if g2 and g2.group(1) not in self.insert_code:
                    self.attrs["grade"] = g2.group(1)
            iso_g = re.search(r"(?<![\w.])([PMKNSH])\s?(\d{1,2})(?![\w.])", up)
            if iso_g:
                self.attrs["iso_group"] = iso_g.group(1)
            if "iso_group" not in self.attrs:
                mi = material_iso(low)
                if mi:
                    self.attrs["iso_group"] = mi
            op = operation_from_text(low)
            if op:
                self.attrs["operation"] = op

        # B5: материал для drill/mill/tap — нержавейка→HSS-E/inox+ISO M, сталь→P,
        # чугун→K, алюминий→N, титан→S.
        if self.family in ("drill", "mill", "tap", "reamer") and "material" not in self.attrs:
            mi = material_iso(low)
            if mi:
                self.attrs["iso_group"] = mi
            mat_common = extract_common(low)
            if mat_common.get("material"):
                self.attrs["material"] = mat_common["material"]

        b = re.search(r"(?:бренд|марка|производител[ья])\s*[:—-]?\s*([a-zа-я0-9-]{2,20})", low)
        if b:
            self.brand = b.group(1)

        common = extract_common(low)
        # В коде державки «M16» - размер пластины, а не метрическая резьба.
        # Вставки (кроме резьбовых) не имеют резьбы G — не ловим G\d+ внутри кода пластины (B10).
        thread = None if self.family in ("holder", "insert") else extract_thread(self.text)
        if thread:
            self.thread = thread.get("thread")
            for key in ("pitch_mm", "diameter_mm", "thread_type", "tap_kind"):
                if thread.get(key) is not None:
                    self.attrs[key] = thread[key]
        self.attrs.update({k: v for k, v in common.items() if k not in self.attrs and k != "grade"})

        teeth = extract_teeth(self.text)
        if teeth is None:
            m = re.search(r"(?<![\w.])(\d{1,2})\s*T(?![A-Za-zА-Яа-я0-9])", self.text)
            if not m:
                m = re.search(r"(?<![\w.])(\d{1,2})\s*Z(?![A-Za-zА-Яа-я0-9])", self.text, re.I)
            if m and 0 < int(m.group(1)) <= 40:
                teeth = int(m.group(1))
        if teeth:
            self.attrs["teeth"] = teeth

        # насадные/торцевые фрезы: «BAP 400R 63-22-4T» — диаметр 63, посадка 22, 4 зуба
        fm = re.search(r"(?<![\w.])(\d{2,3})\s*-\s*(\d{1,3})\s*-\s*(\d{1,2})\s*T(?![A-Za-zА-Яа-я])", self.text, re.I)
        if fm and self.family == "mill":
            self.attrs["diameter_mm"] = float(fm.group(1))
            self.attrs["bore_mm"] = float(fm.group(2))
            self.attrs["teeth"] = int(fm.group(3))
            self.attrs.pop("radius_mm", None)

        dia = _RE_DIA.search(self.text)
        if dia:
            self.attrs["diameter_mm"] = float(dia.group(1).replace(",", "."))
        elif self.family in ("drill", "mill", "reamer", "countersink", "saw"):
            mm = _RE_MM.search(self.text)
            dims = _dims(self.text)
            if mm:
                self.attrs["diameter_mm"] = float(mm.group(1).replace(",", "."))
            elif dims:
                self.attrs["diameter_mm"] = dims[0]

        if self.family in ("drill", "mill") and "диаметр" in low:
            m = re.search(r"(\d+(?:[.,]\d+)?)", low.split("диаметр", 1)[1])
            if m:
                self.attrs["diameter_mm"] = float(m.group(1).replace(",", "."))

        if "diameter_mm" not in self.attrs and self.family in ("drill", "mill", "reamer", "countersink", "saw"):
            teeth = self.attrs.get("teeth")
            nominal = self.attrs.get("diameter_mm") if self.attrs.get("thread_type") else None
            for m in re.finditer(r"(?<![A-Za-zА-Яа-я0-9.])(\d+(?:[.,]\d+)?)(?![A-Za-zА-Яа-я0-9.,])", self.text):
                val = float(m.group(1).replace(",", "."))
                if not (0.3 <= val <= 500):
                    continue
                if teeth and val == teeth:
                    continue
                if nominal and abs(val - float(nominal)) < 1e-9:
                    continue
                self.attrs["diameter_mm"] = val
                break

        if self.family == "drill" and self.thread and re.search(r"под\s+(резьб|метчик)", low):
            td = tap_drill_for(self.thread)
            if td:
                self.attrs["diameter_mm"] = td["drill_mm"]
                self.attrs["tap_drill_for"] = self.thread

        if self.family in ("drill", "mill"):
            ld = re.search(r"(?<![A-Za-z0-9])(\d{1,2})\s*[Dd](?![A-Za-z0-9])", self.text)
            if ld and 1 <= int(ld.group(1)) <= 30:
                self.attrs["ld_ratio"] = int(ld.group(1))
            ang = re.search(r"(?<!\d)(\d{2,3})\s*(?:°|град)", self.text)
            if ang and 45 <= int(ang.group(1)) <= 180:
                self.attrs["angle_deg"] = float(ang.group(1))

        r = re.search(r"(?<![A-Za-zА-Яа-я0-9])R\s*(\d+(?:[.,]\d+)?)", self.text, re.I)
        if r:
            self.attrs["radius_mm"] = float(r.group(1).replace(",", "."))

        m = re.search(r"(?:хв\.?\s*|хвост[а-яё]*\s*)(\d{1,3}(?:[.,]\d+)?)(?!\d)", low)
        if not m:
            # «под 20 хвостовик»: размер стоит перед словом, а не после
            m = re.search(r"\bпод\s+(\d{1,3}(?:[.,]\d+)?)\s*(?:мм\s*)?(?:хв\.?|хвост[а-яё]*)", low)
        if m:
            val = float(m.group(1).replace(",", "."))
            if 1 <= val <= 200:
                if "tool_holder" in self.category_hints:
                    # «держатель осевого инструмента под хвостовик 20»: 20 мм —
                    # хвост зажимаемого инструмента, а не хвостовик самого держателя
                    self.attrs["clamp_mm"] = val
                else:
                    # «хвост 16» — круглый хвостовик диаметром 16 мм, а не квадрат 16×16
                    self.attrs["shank_mm"] = val
                    self.shank_round = True

        if self.family == "holder" and "shank_mm" not in self.attrs:
            # «державка расточная S20»: буква типа хвоста и диаметр, как в начале кода ISO 5608
            m = re.search(r"(?<![A-Za-zА-Яа-яЁё0-9])[SCEHСЕН](\d{2})(?![A-Za-zА-Яа-яЁё0-9])", code_text, re.I)
            if m and 8 <= int(m.group(1)) <= 50:
                if compact(self.holder_code or "") == compact(m.group(0)):
                    self.holder_code = None  # «S20» — обозначение хвоста, а не полный код державки
                self.attrs["shank_mm"] = float(m.group(1))
                self.shank_round = True

        dims = _dims(self.text)
        if self.family == "holder" and "shank_mm" not in self.attrs:
            sec = re.search(r"(?<!\d)(\d{2})(\d{2})(?!\d)", code_text)
            if sec and sec.group(1) == sec.group(2) and 8 <= int(sec.group(1)) <= 50:
                self.attrs["shank_mm"] = float(sec.group(1))
                self.attrs["shank_section"] = sec.group(0)
        if dims and self.family == "holder" and "shank_mm" not in self.attrs:
            self.attrs["shank_mm"] = dims[0]

        if self.family == "holder" and "shank_mm" not in self.attrs:
            # «державка расточная 16»: голое число — диаметр хвоста (круглый хвостовик).
            # «державка 20»: сечение 20×20 (квадратный хвостовик наружной державки).
            for m in re.finditer(r"(?<![\d.])\b(\d{1,3})(?!\d)", code_text):
                val = int(m.group(1))
                if 8 <= val <= 50:
                    if "holder_internal" in self.category_hints or self.shank_round:
                        self.attrs["shank_mm"] = float(val)
                        self.shank_round = True
                    else:
                        self.attrs["shank_mm"] = float(val)
                        self.attrs["shank_section"] = f"{val}×{val}"
                    break

        m = re.search(r"(?:h8|h7|h9|h6)\b", low)
        if m and self.family == "reamer":
            self.attrs["tolerance"] = m.group(0).upper()

        m = re.search(r"(?:er|er-)\s?(\d{1,2})", low)
        if m and self.family == "accessory":
            self.attrs["collet_series"] = f"ER{m.group(1)}"
            # «ER32 12», «ER32-12»: диаметр зажима идёт после серии; «ER16» — только серия
            clamp = re.search(r"(?:er-?\d{1,2})(?!\d)\D{0,4}(\d{1,2}(?:[.,]\d)?)\s*(?:мм)?\b", low)
            if clamp:
                self.attrs["clamp_mm"] = float(clamp.group(1).replace(",", "."))

        if self.family == "mill" and ("дисков" in low or "пазов" in low or "отрезн" in low):
            dims = _dims(self.text)
            if len(dims) >= 2 and dims[1] <= 20:
                self.attrs["thickness_mm"] = dims[1]

        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:мм)?\s*(?:диаметр|ø|⌀)", low)
        if m and "diameter_mm" not in self.attrs and self.family in ("drill", "mill", "reamer"):
            self.attrs["diameter_mm"] = float(m.group(1).replace(",", "."))

        stop = {
            "пластина", "пластины", "пластину", "пластин", "пластиной", "для", "под", "точения", "обработки", "нужна", "нужен", "подбери",
            "посоветуй", "какой", "какая", "купить", "есть", "в", "наличии", "на", "складе", "мне",
            "надо", "хочу", "сверло", "сверла", "фреза", "фрезы", "метчик", "метчика", "державка",
            "державки", "мм", "шт", "цена", "стоимость", "сколько", "стоит", "с", "и", "или",
        }
        self.free_tokens = [t for t in tokenize(_apply_aliases(self.text))
                            if t not in stop and len(t) > 1 and not re.fullmatch(r"\d+[.,]?\d*", t)]
        if self.compat_insert:
            self.free_tokens = [t for t in self.free_tokens if t != self.compat_insert.lower()]
        if self.holder_compat_code:
            hc = compact(self.holder_compat_code)
            self.free_tokens = [t for t in self.free_tokens if compact(t) not in hc]

    def _parse_plate_spec(self, low: str) -> None:
        """«Ромб. Размер 09. Радиус 02»: пластина описана словами, без кода."""
        for pattern, letter in PLATE_SHAPE_WORDS:
            if re.search(pattern, low):
                self.attrs["plate_shape"] = letter
                break
        m = re.search(r"размер\w*\s*[:.—-]?\s*(\d{1,2})(?!\d)", low)
        if m:
            self.attrs["plate_size"] = m.group(1).zfill(2)
        r = re.search(r"радиус\w*\s*[:.—-]?\s*(\d{2}(?:[.,]\d+)?|\d+[.,]\d+|\d{1,2})(?!\d)", low)
        if r:
            raw = r.group(1).replace(",", ".")
            # «02» — код радиуса пластины (0,2 мм), «0,8» и «2» — уже миллиметры
            val = int(raw) / 10.0 if (len(raw) == 2 and raw.isdigit()) else float(raw)
            if 0 < val <= 10:
                self.attrs["corner_radius_mm"] = val
        if self.family == "holder":
            if re.search(r"\bправ", low):
                self.attrs["hand"] = "R"
            elif re.search(r"\bлев", low):
                self.attrs["hand"] = "L"
            # «под пластину Ромб. Размер 09. Правая»: код пластины не назван, но форма,
            # размер и рука есть — по ним и подбираем совместимую державку
            if (self.compat_requested and self.attrs.get("plate_shape")
                    and self.attrs.get("plate_size")):
                self.compat_shape = self.attrs["plate_shape"]
                self.compat_size = self.attrs["plate_size"]
                self.compat_hand = self.attrs.get("hand")

    def _parse_compat_insert(self) -> Optional[Tuple[int, int]]:
        """Фрагмент «под <код пластины>» -> поля совместимости; возвращает его границы."""
        for m in _RE_UNDER_INSERT.finditer(self.text):
            raw = m.group(1).lower().replace("ё", "е")
            if raw in {"резьбу", "резьбы", "пластину", "пластины", "пластин", "метчика", "метчик"}:
                continue
            word = insert_prefix_from_word(m.group(1), self._insert_prefixes)
            digits = m.group(2) or ""
            if not word:
                continue
            if not digits and word not in self._insert_prefixes and word not in _COMMON_INSERT_PREFIXES:
                continue
            self._set_compat(word + digits)
            return m.start(), m.end()
        return None

    def _set_compat(self, code: str) -> None:
        info = insert_compat_key(code)
        if not info:
            return
        self.compat_insert = code.upper()
        self.compat_prefix = info["prefix"]
        self.compat_shape = info["shape"]
        self.compat_clearance = info["clearance"]
        self.compat_hole = info.get("hole")
        self.compat_size = info["size"]


# --------------------------------------------------------------------------------------------------
# Совместимость и подсверловка
# --------------------------------------------------------------------------------------------------
TAP_DRILL = {
    "M1": 0.75, "M1.2": 0.95, "M1.6": 1.25, "M2": 1.6, "M2.5": 2.05, "M3": 2.5, "M4": 3.3,
    "M5": 4.2, "M6": 5.0, "M8": 6.8, "M10": 8.5, "M12": 10.2, "M14": 12.0, "M16": 14.0,
    "M18": 15.5, "M20": 17.5, "M22": 19.5, "M24": 21.0, "M27": 24.0, "M30": 26.5,
}

HOLDER_SHAPE = {"C": "C", "D": "D", "V": "V", "W": "W", "T": "T", "S": "S", "R": "R", "K": "K"}
INSERT_LETTER = {"C": "CNMG/CCMT", "D": "DNMG/DCMT", "V": "VNMG/VCMT", "W": "WNMG/WCMT", "T": "TNMG/TCMT", "S": "SNMG/SCMT", "R": "RNMG/RCMT"}

# R1: тип зажима державки -> допустимые типы отверстия пластины (4-я буква ISO 1832).
# C - без отверстия (N/R/F), D/M/P - цилиндрическое (A/M/G), S - коническое (T/W/Q/U).
CLAMP_HOLE = {"C": set("NRF"), "D": set("AMG"), "M": set("AMG"), "P": set("AMG"), "S": set("TWQU")}


def clamp_accepts_hole(clamp: Optional[str], hole: Optional[str]) -> bool:
    """Зажим C требует пластину без отверстия, S - с коническим; неизвестное не ограничиваем."""
    allowed = CLAMP_HOLE.get((clamp or "").upper())
    if not allowed or not hole:
        return True
    return (hole or "").upper() in allowed


def tap_drill_for(thread: Optional[str]) -> Optional[Dict[str, Any]]:
    if not thread:
        return None
    m = re.match(r"M(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?", thread.upper())
    if not m:
        return None
    d = float(m.group(1))
    p = float(m.group(2)) if m.group(2) else None
    std = TAP_DRILL.get(f"M{int(d)}" if d == int(d) else f"M{d}")
    dia = round(d - p, 2) if p else std
    if dia is None:
        return None
    return {"thread": thread, "drill_mm": dia, "nominal_mm": d, "pitch_mm": p}


def holder_insert_hint(code: Optional[str]) -> Optional[str]:
    info = parse_holder_code(code)
    if not info or not info.get("turning") or not info.get("insert_size"):
        return None
    shape = info.get("shape")
    return f"{INSERT_LETTER.get(shape, shape)} {info['insert_size']}xxxx"


def holder_insert_compat(code: Optional[str]) -> Optional[Dict[str, Any]]:
    """MCLNR2525M12 -> форма C, задний угол N, пластина 12, сечение 25 мм.

    Сам разбор кода - в iso5608; здесь оставляем поля, на которые опирается поиск.
    """
    info = parse_holder_code(code)
    if not info:
        return None
    return {
        "shape": info.get("shape"),
        "clearance": info.get("clearance"),
        "size": info.get("insert_size"),
        "shank_mm": info.get("shank_mm"),
        "shank_diameter_mm": info.get("shank_diameter_mm"),
        "clamp": info.get("clamp"),
        "hand": info.get("hand"),
        "kind": info.get("kind"),
        "series_key": info.get("series_key"),
        "turning": bool(info.get("turning")),
    }


def insert_compat_key(code: Optional[str]) -> Dict[str, Any]:
    """CNMG1204 -> форма C, задний угол N, размер 12; APMT -> только префикс."""
    letters = re.match(r"[A-Z]+", (code or "").upper())
    if not letters:
        return {}
    pref = letters.group(0)
    digits = (code or "").upper()[len(pref):]
    return {
        "prefix": pref,
        "shape": pref[0],
        "clearance": pref[1] if len(pref) >= 2 else None,
        "hole": pref[3] if len(pref) >= 4 else None,
        "size": digits[:2] if len(digits) >= 2 else None,
    }


_RE_UNDER_INSERT = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])под\s+(?:пластин[а-яё]*\s+)?([A-Za-zА-Яа-яЁё]{2,6})\s*(\d{2,6}(?:[A-Z]\d{2,4})*)?", re.I
)
_RE_COMPAT_PHRASE = re.compile(r"\bпод\s+пластин[а-яё]*\b", re.I)
_RE_PLATE_WORD = re.compile(r"\bпластин[а-яё]*\b", re.I)
_RE_HOLDER_MENTION = re.compile(r"\bдержавк[а-яё]*\b", re.I)
_RE_PAREN_INSERT = re.compile(r"\(([A-Z]{2,5}\d{2,4})")


# «под хвостовик 20»: размер назван, но после «под» — значит, это ограничение
# к предыдущему запросу, а не новый инструмент.
_RE_UNDER_SIZE = re.compile(
    r"\bпод\s+(?:мм\s+)?(?:хвост[а-яё]*|сечени[а-яё]*|диаметр[а-яё]*|хв\.?)", re.I
)
# «под пластину DNMG15»: само слово «пластина» — часть уточнения, а не запрос «пластины».
_RE_UNDER_PLATE = re.compile(r"\bпод\s+пластин[а-яё]*", re.I)
# Замкнутый набор слов-уточнителей: служебные слова и прилагательные вида обработки.
# Только словоформы: голые основы («расточн») — не слова и не уточнение.
_ADJ_TAIL = r"(?:ая|яя|ое|ее|ой|ей|ою|ею|ую|юю|ые|ие|ых|их|ым|им|ыми|ими|ом|ем|ый|ий|ого|его|ому|ему)"
_CLARIFY_ADJ = (
    "чистов", "получистов", "чернов", "наружн", "внутренн", "расточн", "канавочн",
    "резьбов", "проходн", "подрезн", "торцев", "торцов", "концев", "дисков",
    "сферическ", "радиусн", "лев", "прав", "сменн",
)
_RE_CLARIFY_WORD = re.compile(
    r"(?:" + "|".join(["под", "для", "по", "мм", r"обработк[а-яё]*"]
                      + [stem + _ADJ_TAIL for stem in _CLARIFY_ADJ]) + r")", re.I
)
_RE_NUMBER = re.compile(r"\d+(?:[.,]\d+)?(?:[xх]\d+(?:[.,]\d+)?)?")
# Резьба: M10 — размер в уточнении. «S20»/«SK40» сюда не попадают: это обозначение инструмента.
_RE_THREAD_SIZE = re.compile(r"m\d{1,4}(?:[.,]\d+)?", re.I)
_RE_TOKEN = re.compile(r"[a-zа-яё0-9]+(?:[.,][0-9]+)*(?:[xх][0-9]+(?:[.,][0-9]+)*)?")


def is_clarification(text: str, insert_prefixes: Optional[Iterable[str]] = None) -> bool:
    """Уточнение к предыдущему запросу: «12», «под CNMG12», «чистовая», «под хвостовик 20».

    Уточнения — замкнутый набор: число, слово-уточнитель, префикс пластины без размера.
    Всё незнакомое («MTA2 велдон 10», «SK40», «HSK63», «ER32») и код с размером
    («cnmg12», «DCGT 11») — новый запрос, даже если короткое: иначе сообщение со своим
    обозначением склеивалось с предыдущей выдачей и повторяло её.
    """
    low = (text or "").lower().replace("ё", "е").strip()
    if not low:
        return True
    known = {p.upper() for p in (insert_prefixes or ())} | _COMMON_INSERT_PREFIXES
    # «под CNMG12» / «под APMT1604» — уточнение: код после «под» снимаем с проверки на полноту
    rest = _RE_UNDER_INSERT.sub(
        lambda m: " под " if insert_prefix_from_word(m.group(1), known) in known else m.group(0), low
    )
    rest = _RE_UNDER_SIZE.sub(" под ", rest)
    rest = _RE_UNDER_PLATE.sub(" под ", rest)
    code = insert_code_from_text(rest, known)
    if code:
        return False  # полный код пластины («CNMG 120408») — самостоятельный запрос
    if holder_code_from_text(rest):
        return False  # структурно полный код оснастки («PCLNR 2525M12», «MCBNR2020»)
    # «DCGT 11», «CNMG 12»: код пластины с размером через пробел — самостоятельный запрос
    short = re.search(r"(?<![a-z0-9])([a-z]{2,5})\s?(\d{2})(?![a-z0-9])", rest)
    if short:
        pref = insert_prefix_from_word(short.group(1), known)
        if pref in known and pref[1] in _ISO_CLEARANCE:
            return False
    for tok in _RE_TOKEN.findall(rest):
        if _RE_NUMBER.fullmatch(tok) or _RE_THREAD_SIZE.fullmatch(tok) or _RE_CLARIFY_WORD.fullmatch(tok):
            continue
        # голый префикс без размера («cnmg», «dcmt») — уточнение к предыдущему запросу;
        # код с размером («cnmg12», «DCGT 11») — самостоятельный запрос, иначе он
        # склеивался с предыдущей выдачей и повторял её
        head = re.fullmatch(r"([a-zа-яё]{2,6})(\d*)", tok)
        if (head and not head.group(2)
                and insert_prefix_from_word(head.group(1), known) in known):
            continue
        return False
    return True


def is_self_contained_query(text: str) -> bool:
    """«метчик M10», «державка 2020 под CNMG12», «mcbnr 2020» — новый запрос, а не уточнение."""
    return not is_clarification(text)


def mill_insert_codes(name: str) -> List[str]:
    """Корпуса фрез: «под APMT1604**», «(APKT1604**)» -> ['APMT1604', 'APKT1604']."""
    out: List[str] = []
    for m in _RE_UNDER_INSERT.finditer(name or ""):
        raw = m.group(1).lower().replace("ё", "е")
        if raw in {"резьбу", "резьбы", "пластину", "пластины", "пластин", "метчика", "метчик"}:
            continue
        word = insert_prefix_from_word(m.group(1))
        if not word:
            continue
        code = word + (m.group(2) or "")
        if code not in out:
            out.append(code)
    for m in _RE_PAREN_INSERT.finditer((name or "").upper()):
        code = m.group(1)
        if code[0] not in _INSERT_SHAPES:  # «(YS25)» — марка, а не пластина
            continue
        if code not in out:
            out.append(code)
    return out


# --------------------------------------------------------------------------------------------------
# Поисковый движок
# --------------------------------------------------------------------------------------------------
class CatalogSearchEngine:
    def __init__(self, items: Optional[List[Dict[str, Any]]] = None):
        self.items: List[Dict[str, Any]] = []
        self.by_family: Dict[str, List[Dict[str, Any]]] = {}
        self.df: Dict[str, int] = {}
        self.total = 0
        self._vocab: set = set()
        self._vocab_by_len: Dict[int, List[str]] = {}
        self._corr_cache: Dict[str, Optional[str]] = {}
        self._insert_prefixes: Dict[str, int] = {}
        # (family, compact_code) -> индексы позиций в self.items для быстрого точного поиска кода
        self._by_family_and_code: Dict[Tuple[str, str], List[int]] = {}
        # token -> set(item indices) — инвертированный индекс токенов (S5)
        self._posting_lists: Dict[str, set] = {}
        # LRU-кэш результатов поиска по нормализованному запросу (S5)
        self._search_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._cache_max_size = 256
        self._catalog_mtime: float = 0.0
        if items:
            self.load(items)

    # ---- загрузка и индексы ----------------------------------------------------------------------
    def load(self, items: Sequence[Dict[str, Any]]) -> None:
        self.items = [it for it in items if it.get("family") and it.get("family") != "other"]
        self.by_family = {}
        doc_tokens: List[set] = []
        df: Dict[str, int] = {}
        vocab = set()
        prefixes: Dict[str, int] = {}
        for idx, it in enumerate(self.items):
            attrs = it.get("attrs")
            if not attrs:
                attrs = it["attrs"] = {}
            iso = str(attrs.get("iso_code") or "").strip().upper()
            if len(iso) >= 4:
                prefixes[iso[:4]] = prefixes.get(iso[:4], 0) + 1
            if it["family"] == "holder":
                info = holder_insert_compat(str(attrs.get("holder_code") or it.get("sku") or ""))
                if info:
                    it["_insert_compat"] = info
                    dia = info.get("shank_diameter_mm")
                    if dia:
                        # расточная державка: хвост круглый, диаметр из кода точнее разбора названия
                        attrs["shank_mm"] = dia
                        attrs["shank_diameter_mm"] = dia
                        attrs.pop("shank_section", None)
                    elif info.get("shank_mm") and not attrs.get("shank_mm"):
                        attrs["shank_mm"] = info["shank_mm"]
                        side = int(info["shank_mm"])
                        attrs.setdefault("shank_section", f"{side}×{side}")
            elif it["family"] == "mill":
                codes = mill_insert_codes(str(it.get("name") or ""))
                if codes:
                    it["_mill_inserts"] = codes
                    attrs["compatible_inserts"] = ", ".join(codes)
            elif it["family"] == "accessory" and it.get("category") == "tool_holder":
                # «SBHA12-20 ...»: 12 — хвостовик держателя, 20 — хвост зажимаемого инструмента
                m = re.search(r"SBHA\)?\s*(\d{2})\s*[-–]\s*(\d{2})(?:\s*[-–]\s*(\d{2,3}))?",
                              str(it.get("name") or "").upper())
                if m:
                    attrs.setdefault("shank_mm", float(m.group(1)))
                    attrs.setdefault("clamp_mm", float(m.group(2)))
                    if m.group(3):
                        attrs.setdefault("length_mm", float(m.group(3)))
            text = " ".join(str(x) for x in (
                it.get("sku"), it.get("name"), it.get("brand"), it.get("category"),
                attrs.get("iso_code"), attrs.get("holder_code"), attrs.get("grade"),
                attrs.get("thread"), attrs.get("coating"), attrs.get("standard"),
            ) if x)
            toks = set(tokenize(text))
            it["_tokens"] = toks
            it["_compact"] = compact(f"{it.get('sku')} {it.get('name')}")
            # имена с кириллическими омоглифами («К11-400») сравниваем в латинице
            it["_name_norm"] = compact(homoglyph_latin(str(it.get("name") or "")))
            code_src = " ".join(str(x) for x in (it.get("sku"), attrs.get("iso_code"), attrs.get("holder_code")) if x)
            it["_code_compact"] = compact(code_src)
            it["_brand_norm"] = compact(it.get("brand", ""))
            # предвычисленные compact-коды для быстрого точного поиска (S1, S2)
            iso_c = compact(str(attrs.get("iso_code") or ""))
            holder_c = compact(str(attrs.get("holder_code") or ""))
            sku_c = compact(str(it.get("sku") or ""))
            it["_iso_compact"] = iso_c
            it["_holder_compact"] = holder_c
            it["_sku_compact"] = sku_c
            it["_dedupe_key"] = (it["_brand_norm"], sku_c or compact(it.get("name", "")))
            fam = it["family"]
            for code in {iso_c, holder_c, sku_c}:
                if code and len(code) >= 4:
                    self._by_family_and_code.setdefault((fam, code), []).append(idx)
            doc_tokens.append(toks)
            for t in toks:
                df[t] = df.get(t, 0) + 1
                if len(t) >= 4 and any(ch.isdigit() for ch in t):
                    vocab.add(t)
                # S5: инвертированный индекс токенов — token -> set(item indices)
                self._posting_lists.setdefault(t, set()).add(idx)
            self.by_family.setdefault(it["family"], []).append(it)
        self.df = df
        self.total = len(self.items)
        self._vocab = vocab
        self._insert_prefixes = prefixes
        by_len: Dict[int, List[str]] = {}
        for token in vocab:
            by_len.setdefault(len(token), []).append(token)
        self._vocab_by_len = by_len
        self._corr_cache = {}
        # инвалидируем кэш поиска при перезагрузке каталога
        self._search_cache.clear()
        try:
            self._catalog_mtime = os.path.getmtime(SITE_CSV)
        except OSError:
            self._catalog_mtime = 0.0

    def reload(self, path: Optional[str] = None) -> int:
        from src.site_catalog import load_site_catalog
        self.load(load_site_catalog(path) if path else load_site_catalog())
        return self.total

    # ---- утилиты ---------------------------------------------------------------------------------
    def _idf(self, tok: str) -> float:
        df = self.df.get(tok, 0)
        return math.log((self.total - df + 0.5) / (df + 0.5) + 1.0) if self.total else 0.0

    def _text_score(self, it: Dict[str, Any], tokens: Sequence[str]) -> float:
        if not tokens:
            return 0.0
        doc = it.get("_tokens") or set()
        score = 0.0
        for t in tokens:
            if t in doc:
                score += self._idf(t)
            elif len(t) >= 5 and any(ch.isdigit() for ch in t):
                fixed = self._correct(t)
                if fixed and fixed in doc:
                    score += self._idf(fixed) * 0.6
        return score

    def _correct(self, tok: str) -> Optional[str]:
        if tok in self._corr_cache:
            return self._corr_cache[tok]
        result = None
        if tok in self._vocab:
            result = tok
        elif len(tok) >= 5:
            for length in (len(tok) - 1, len(tok), len(tok) + 1):
                for cand in self._vocab_by_len.get(length, ()):
                    if damerau(tok, cand) <= 1:
                        result = cand
                        break
                if result:
                    break
        self._corr_cache[tok] = result
        return result

    def _canonical_insert_code(self, code: str) -> str:
        """Опечатка/раскладка в префиксе кода: «СТМН 120408» -> CTMN -> CNMG.

        Префикс заменяется, только если его нет в каталоге, а похожий (Дамерау <= 2,
        та же форма) есть. Реальные коды каталога не трогаем.
        """
        if not code or len(code) < 4:
            return code
        pref = code[:4].upper()
        # Известные префиксы пластин не «исправляем», даже если таких позиций нет в текущем срезе:
        # иначе CCMT1204 (нет в каталоге) превратился бы в CNMG1204 и подбор шёл бы под чужую пластину.
        if pref in self._insert_prefixes or pref in _COMMON_INSERT_PREFIXES:
            return code
        cands = []
        for known, cnt in self._insert_prefixes.items():
            if known[0] != pref[0]:
                continue
            dist = damerau(pref, known, 2)
            if dist <= 2:
                cands.append((dist, -cnt, known))
        if not cands:
            return code
        cands.sort()
        return cands[0][2] + code[4:]

    @staticmethod
    def _code_match(item: Dict[str, Any], code: str) -> Tuple[int, str]:
        """0 нет, 1 часть кода (запрос короче), 2 вхождение в артикул, 3 полный код."""
        want = compact(code)
        if not want:
            return 0, ""
        attrs = item.get("attrs") or {}
        iso = compact(str(attrs.get("iso_code") or ""))
        if iso and iso == want:
            return 3, "код"
        if compact(str(attrs.get("holder_code") or "")) == want:
            return 3, "код"
        sku = compact(str(item.get("sku") or ""))
        if sku.startswith(want):
            after = sku[len(want):len(want) + 1]
            return (1, "часть кода") if after.isdigit() else (3, "код")
        if iso and want in iso:
            return 1, "часть кода"
        have = item.get("_code_compact") or ""
        if have and want in have:
            return 2, "код"
        return 0, ""

    # ---- фильтры ---------------------------------------------------------------------------------
    def _filters(self, q: Query, fam: str):
        """[(имя, жёсткий, функция(item)->bool)] — порядок задаёт лесенку ослаблений."""
        a = q.attrs
        out = []
        if fam == "insert":
            if q.insert_code:
                # короткая запись «DCGT09»: сверяем префикс, размер отсекается отдельно,
                # иначе при отсутствии размера фильтр кода убивает всю выдачу
                want_code = a.get("insert_prefix") or q.insert_code
                out.append(("код", True, lambda it: self._code_match(it, want_code)[0] > 0))
            if q.holder_compat:
                out.append(("под державку", True, lambda it: self._insert_fits_holder(it, q)))
            if a.get("iso_tail"):
                # «DCGT 11T302» — точное обозначение пластины: 11T302, а не любой размер 11
                want_iso = compact(q.insert_code + a["iso_tail"])
                out.append(("полный код", True, lambda it: (
                    compact(str((it["attrs"] or {}).get("iso_code") or "")) == want_iso)))
            if a.get("size_code"):
                out.append(("размер", True, lambda it: str((it["attrs"] or {}).get("size_code") or "").zfill(2) == str(a["size_code"]).zfill(2)))
            if a.get("plate_shape"):
                out.append(("форма", True, lambda it: (
                    str((it["attrs"] or {}).get("insert_shape") or "").upper() == a["plate_shape"])))
            if a.get("plate_size"):
                out.append(("размер", True, lambda it: (
                    str((it["attrs"] or {}).get("size_code") or "").zfill(2) == a["plate_size"])))
            if a.get("corner_radius_mm"):
                out.append(("радиус", False, lambda it: self._near(
                    it["attrs"].get("corner_radius_mm"), a["corner_radius_mm"], 0.02)))
            if a.get("diameter_mm") and not q.insert_code:
                out.append(("диаметр", False, lambda it: self._near(it["attrs"].get("diameter_mm"), a["diameter_mm"], 0.15)))
            if a.get("pitch_mm"):
                out.append(("шаг", False, lambda it: self._near(it["attrs"].get("pitch_mm"), a["pitch_mm"], 0.02)))
            if a.get("radius_mm"):
                out.append(("радиус", False, lambda it: self._near(it["attrs"].get("radius_mm"), a["radius_mm"], 0.05)))
            if a.get("iso_group"):
                out.append(("группа ISO", False, lambda it: (
                    str((it["attrs"].get("iso_group") or "")).upper() == a["iso_group"].upper()
                    or a["iso_group"].upper() in str(it["attrs"].get("secondary_iso") or "").upper()
                )))
            if a.get("operation"):
                out.append(("вид обработки", False, lambda it: (it["attrs"].get("operation") or "") == a["operation"]))
            if a.get("grade"):
                want_grade = compact(str(a["grade"]))
                # марка в названии — отдельным токеном: «… FL K10», но не «ALU AK10»
                grade_re = re.compile(rf"(?<![A-Za-z0-9]){re.escape(want_grade)}(?![A-Za-z0-9])", re.I)
                out.append(("марка", False, lambda it: (
                    compact(str(it["attrs"].get("grade") or "")) == want_grade
                    or bool(grade_re.search(homoglyph_latin(str(it.get("name") or ""))))
                )))
        elif fam in ("drill", "mill", "reamer"):
            if fam == "mill" and q.compat_insert:
                out.append(("под пластину", True, lambda it: self._mill_fits(it, q)))
            if a.get("diameter_mm"):
                tol = 0.06 if a["diameter_mm"] < 10 else 0.11
                out.append(("диаметр", True, lambda it: self._near(it["attrs"].get("diameter_mm"), a["diameter_mm"], tol)))
            # B5: материал для свёрел/фрез/разверток — нержавейка→HSS-E/inox+ISO M, сталь→P, чугун→K, алюминий→N, титан→S
            if a.get("material"):
                want_mat = compact(str(a["material"]))
                out.append(("материал", False, lambda it: (
                    want_mat in compact(str(it["attrs"].get("material") or ""))
                    or compact(str(it["attrs"].get("material") or "")) in want_mat
                )))
            if a.get("iso_group"):
                out.append(("группа ISO", False, lambda it: (
                    str((it["attrs"].get("iso_group") or "")).upper() == a["iso_group"].upper()
                    or a["iso_group"].upper() in str(it["attrs"].get("secondary_iso") or "").upper()
                )))
            if a.get("teeth"):
                out.append(("зубья", False, lambda it: self._int_eq(it["attrs"].get("teeth"), a["teeth"])))
            if a.get("shank_mm"):
                out.append(("хвостовик", False, lambda it: self._near(it["attrs"].get("shank_mm"), a["shank_mm"], 0.5)))
            if a.get("radius_mm") and fam == "mill":
                out.append(("радиус", False, lambda it: self._near(it["attrs"].get("radius_mm"), a["radius_mm"], 0.05)))
            if a.get("thickness_mm") and fam == "mill":
                out.append(("толщина", False, lambda it: self._near(it["attrs"].get("thickness_mm"), a["thickness_mm"], 0.15)))
            if a.get("ld_ratio") and fam == "drill":
                out.append(("класс длины", False, lambda it: self._int_eq(it["attrs"].get("ld_ratio"), a["ld_ratio"])))
            if a.get("flutes2") and fam == "mill":
                # шпоночная фреза: два зуба (2F / z2), у резьбофрез и ласточкиных хвостов их больше
                out.append(("2 зуба", True, lambda it: bool(re.search(
                    r"(?<![A-Z0-9])2\s*F(?![A-Z])|\bZ\s*=?\s*2(?!\d)|2\s*зуб",
                    str(it.get("name") or "").upper()))))
            if a.get("angle_deg") and fam == "drill":
                out.append(("угол при вершине", False, lambda it: self._near(it["attrs"].get("angle_deg"), a["angle_deg"], 1)))
            if a.get("angle_deg") and fam in ("countersink",):
                out.append(("угол", True, lambda it: self._near(it["attrs"].get("angle_deg"), a["angle_deg"], 1)))
        elif fam in ("tap", "die"):
            if q.thread:
                out.append(("резьба", True, lambda it: self._thread_match(it["attrs"].get("thread"), q.thread, a.get("pitch_mm"))))
            if a.get("tap_kind"):
                out.append(("исполнение", False, lambda it: (it["attrs"].get("tap_kind") or "") == a["tap_kind"]))
        elif fam == "holder":
            if q.compat_insert or (q.compat_shape and q.compat_size):
                out.append(("под пластину", True, lambda it: self._holder_fits(it, q)))
            if q.holder_code:
                out.append(("код", True, lambda it: self._code_match(it, q.holder_code)[0] > 0))
            if a.get("shank_mm"):
                if a.get("shank_section"):
                    out.append(("сечение", True, lambda it: (
                        not it["attrs"].get("shank_diameter_mm")
                        and self._near(it["attrs"].get("shank_mm"), a["shank_mm"], 0.5))))
                else:
                    # «хвост 16», S20: круглый хвостовик, сравниваем диаметр
                    out.append(("диаметр хвоста", True, lambda it: self._near(
                        it["attrs"].get("shank_diameter_mm"), a["shank_mm"], 0.5)))
        elif fam == "countersink":
            if a.get("diameter_mm"):
                out.append(("диаметр", True, lambda it: self._near(it["attrs"].get("diameter_mm"), a["diameter_mm"], 0.2)))
            if a.get("angle_deg"):
                out.append(("угол", False, lambda it: self._near(it["attrs"].get("angle_deg"), a["angle_deg"], 1)))
        elif fam == "saw":
            if a.get("diameter_mm"):
                out.append(("диаметр", True, lambda it: self._near(it["attrs"].get("diameter_mm"), a["diameter_mm"], 0.5)))
            if a.get("teeth"):
                out.append(("зубья", False, lambda it: self._int_eq(it["attrs"].get("teeth"), a["teeth"])))
        elif fam == "accessory":
            if "патрон" in q.low:
                # «патрон» и «оправка» — само изделие: винты и гайки в ответ не идут
                out.append(("изделие", True, lambda it: (
                    "патрон" in str(it.get("name") or "").lower()
                    or "оправк" in str(it.get("name") or "").lower())))
            if re.search(r"сверлильн", q.low):
                out.append(("сверлильный", True, lambda it: (
                    "сверлильн" in str(it.get("name") or "").lower())))
            if "measuring" in q.category_hints:
                if a.get("measure_code"):
                    out.append(("артикул", True, lambda it: (
                        compact(a["measure_code"]) in (it.get("_name_norm") or ""))))
                if a.get("tolerance"):
                    # в названии бывает кириллическое «Н7», сравниваем после замены гомоглифов
                    want_tol = a["tolerance"].upper()
                    out.append(("допуск", True, lambda it: want_tol in re.sub(
                        r"\s+", "", homoglyph_latin(str(it.get("name") or ""))).upper()))
                if a.get("diameter_mm"):
                    out.append(("диаметр", True, lambda it: self._near(
                        gauge_diameter(it.get("name")), a["diameter_mm"], 0.05)))
            if a.get("taper"):
                out.append(("конус", True, lambda it: accessory_mount(it.get("name")).get("taper") == a["taper"]))
            if a.get("weldon"):
                # серия SL/SLN — это и есть посадка Weldon (BT40-SL20-90, BT40-SLN-20-63)
                out.append(("хвостовик Weldon", True, lambda it: bool(
                    re.search(r"WELDON|SLN|(?<![A-Z])SL(?=[\d-])", str(it.get("name") or "").upper()))))
            if a.get("tool_d_mm"):
                out.append(("диаметр хвоста", True, lambda it: self._near(
                    accessory_mount(it.get("name")).get("d"), a["tool_d_mm"], 0.01)))
            if a.get("tool_l_mm"):
                out.append(("длина", True, lambda it: self._near(
                    accessory_mount(it.get("name")).get("l"), a["tool_l_mm"], 0.01)))
            if a.get("chuck_system"):
                out.append(("система", False, lambda it: (
                    compact(a["chuck_system"]) in (it.get("_name_norm") or ""))))
            if a.get("chuck_taper"):
                out.append(("конус патрона", True, lambda it: (
                    compact(a["chuck_taper"]) in (it.get("_name_norm") or ""))))
            # после конуса: ослабление снимает сначала уточнения, конус сохраняется дольше
            if a.get("self_tightening"):
                out.append(("самозажимной", True, lambda it: (
                    "самозажимн" in str(it.get("name") or "").lower())))
            if a.get("chuck_max_mm"):
                out.append(("диаметр зажима", True, lambda it: (
                    chuck_capacity(it.get("name")) == a["chuck_max_mm"])))
            if a.get("clamp_set"):
                out.append(("прижимы", True, lambda it: "прижим" in str(it.get("name") or "").lower()))
            if a.get("slot_mm"):
                out.append(("паз", True, lambda it: slot_mm_from_name(it.get("name")) == a["slot_mm"]))
            if a.get("collet_series"):
                out.append(("серия", True, lambda it: (it["attrs"].get("collet_series") or "").upper() == a["collet_series"].upper()))
            if a.get("jaw_series"):
                want_series = compact(f"{a['jaw_series']}-{a['jaw_size']}")
                out.append(("серия патрона", True, lambda it: want_series in (it.get("_name_norm") or "")))
            if a.get("morse_from"):
                pair = f"{a['morse_from']}/{a['morse_to']}"
                out.append(("переход Морзе", True, lambda it: pair in str(it.get("name") or "")))
                if a.get("with_tang"):
                    out.append(("с лапкой", False, lambda it: "лапк" in str(it.get("name") or "")))
            if a.get("bar_puller"):
                out.append(("барпуллер", True, lambda it: "барпуллер" in str(it.get("name") or "").lower()))
            if a.get("bar_shank_mm"):
                side = f"S{a['bar_shank_mm']}"
                out.append(("квадр. хвост", False, lambda it: (
                    side in str(it.get("name") or "") and "квадр" in str(it.get("name") or ""))))
            if a.get("clamp_mm"):
                want = f"{a['clamp_mm']:g}"
                clamp_name = "под хвостовик" if "tool_holder" in q.category_hints else "диаметр зажима"
                out.append((clamp_name, False, lambda it: (
                    self._near(it["attrs"].get("clamp_mm"), a["clamp_mm"], 0.5)
                    or (not it["attrs"].get("clamp_mm")
                        and (str(it["attrs"].get("clamp_range") or "").endswith("-" + want)
                             or bool(re.search(rf"(?<![\d.]){re.escape(want)}(?:[.,]0)?\s*мм", str(it.get("name") or "")))))
                )))
            if a.get("shank_mm"):
                out.append(("хвостовик", False, lambda it: self._near(it["attrs"].get("shank_mm"), a["shank_mm"], 0.5)))

        if a.get("coating"):
            out.append(("покрытие", False, lambda it: self._same_text(it["attrs"].get("coating"), a["coating"])))
        if a.get("material"):
            out.append(("материал", False, lambda it: self._same_text(it["attrs"].get("material"), a["material"])))
        if a.get("standard"):
            out.append(("стандарт", False, lambda it: compact(a["standard"]) in compact(str(it["attrs"].get("standard") or ""))))
        if a.get("hrc"):
            out.append(("HRC", False, lambda it: (it["attrs"].get("hrc") or 0) >= a["hrc"]))
        if q.brand:
            out.append(("бренд", False, lambda it: it.get("_brand_norm") == compact(q.brand)))
        if q.category_hints:
            out.append(("тип", True, lambda it: it.get("category") in q.category_hints))
        return out

    @staticmethod
    def _round_shank(q: Query) -> bool:
        """Расточная державка: хвост круглый, «сечение 25×25» к ней не относится."""
        return bool(q.shank_round) or "holder_internal" in q.category_hints

    @staticmethod
    def _holder_fits(it: Dict[str, Any], q: Query) -> bool:
        info = it.get("_insert_compat")
        if not info:
            return False
        if info.get("shape") != q.compat_shape:
            return False
        if q.compat_clearance and info.get("clearance") != q.compat_clearance:
            return False
        if q.compat_size and info.get("size") != q.compat_size:
            return False
        if q.compat_hand and info.get("hand") and info.get("hand") != q.compat_hand:
            return False
        if not clamp_accepts_hole(info.get("clamp"), q.compat_hole):
            return False
        return True

    @staticmethod
    def _insert_fits_holder(it: Dict[str, Any], q: Query) -> bool:
        """CNMG120408 в MCLNR2525M12: форма C, задний угол N, размер 12."""
        info = q.holder_compat or {}
        attrs = it.get("attrs") or {}
        src = str(attrs.get("iso_code") or it.get("sku") or "")
        code = compact(src).upper()
        m = re.match(r"[A-Z]+", code)
        if not m or not info.get("size"):
            return False
        pref = m.group(0)
        digits = code[len(pref):]
        if pref[0] != info.get("shape"):
            return False
        if info.get("clearance") and len(pref) > 1 and pref[1] != info["clearance"]:
            return False
        if not clamp_accepts_hole(info.get("clamp"), pref[3] if len(pref) >= 4 else None):
            return False
        return digits[:2] == str(info["size"])

    @staticmethod
    def _mill_fits(it: Dict[str, Any], q: Query) -> bool:
        want = (q.compat_insert or "").upper()
        if not want:
            return False
        for code in it.get("_mill_inserts") or []:
            if code.startswith(want) or want.startswith(code):
                return True
        return False

    @staticmethod
    def _int_eq(value: Any, want: Any) -> bool:
        try:
            return int(float(value)) == int(float(want))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _near(value: Any, want: Any, tol: float) -> bool:
        try:
            return value is not None and abs(float(value) - float(want)) <= tol + 1e-9
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _same_text(value: Any, want: Any) -> bool:
        if not value or not want:
            return False
        return compact(str(value)) == compact(str(want)) or compact(str(want)) in compact(str(value))

    @staticmethod
    def _thread_match(have: Any, want: str, pitch: Any) -> bool:
        if not have:
            return False
        h = re.sub(r"\s+", "", str(have).upper().replace("М", "M").replace("Х", "X").replace("*", "X"))
        w = re.sub(r"\s+", "", str(want).upper().replace("М", "M").replace("Х", "X").replace("*", "X"))
        if h == w:
            return True
        mh = re.match(r"^M(\d+(?:\.\d+)?)", h)
        mw = re.match(r"^M(\d+(?:\.\d+)?)", w)
        if mh and mw and float(mh.group(1)) == float(mw.group(1)):
            if pitch is None:
                return True
            hp = re.search(r"X(\d+(?:\.\d+)?)", h)
            return hp is not None and abs(float(hp.group(1)) - float(pitch)) < 0.01
        return compact(h) == compact(w)

    # ---- основной поиск --------------------------------------------------------------------------
    def search(self, text: str, limit: int = 8, in_stock_only: bool = True,
               pin_names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        q = Query(text, self._insert_prefixes, self._by_family_and_code)
        if q.insert_code:
            q.insert_code = self._canonical_insert_code(q.insert_code)
        if q.compat_insert:
            fixed = self._canonical_insert_code(q.compat_insert)
            if fixed != q.compat_insert:
                q._set_compat(fixed)
        if pin_names:
            pinned = self._search_pinned(q, pin_names, limit, in_stock_only)
            if pinned:
                return pinned
        if q.family is None:
            if q.compat_insert:
                return self._search_compat(q, limit, in_stock_only)
            return self._search_ambiguous(q, limit, in_stock_only)
        if q.compat_requested and not q.compat_insert:
            # «под пластину Ромб 09»: форма и размер названы — код пластины не нужен
            if not (q.family == "holder" and q.compat_shape and q.compat_size):
                return self._compat_ask_code(q)
        if q.holder_compat_requested and not q.holder_compat:
            return self._holder_ask_code(q)
        # B9: группа известна, но нет кода, параметров или категории — просим уточнить,
        # не лить всю семью с уровнем «точное». compatible_insert — уже достаточно для подбора.
        if q.family and not (q.insert_code or q.holder_code or q.attrs or q.category_hints or q.thread or q.compat_insert):
            return self._ask_params(q)
        return self._search_family(q, q.family, limit, in_stock_only)

    def _ask_params(self, q: Query) -> Dict[str, Any]:
        """Группа известна, но нет кода/параметров — просим уточнить запрос."""
        return {
            "query": q.text, "family": q.family, "groups": [], "products": [],
            "parsed": dict(q.attrs), "chips": self._chips(q, q.family),
            "level": "уточните параметры", "total_found": 0, "relaxations": [],
            "follow_ups": self._follow_ups(q, q.family, []),
            "note": f"Укажите параметры для {FAMILY_TITLES.get(q.family, q.family)}: код, диаметр, размер и т.п.",
        }

    def _compat_ask_code(self, q: Query) -> Dict[str, Any]:
        """«Фреза под пластину» без кода пластины: подбирать не под что, просим код."""
        return {
            "query": q.text, "family": q.family, "groups": [], "products": [],
            "parsed": dict(q.attrs), "chips": self._chips(q, q.family),
            "level": "уточните пластину", "total_found": 0, "relaxations": [],
            "follow_ups": [
                "Укажите код пластины, под которую нужен инструмент (например CNMG 120408 или APMT1604)."
            ],
            "note": "Для подбора совместимого инструмента нужен код пластины.",
        }

    def _holder_ask_code(self, q: Query) -> Dict[str, Any]:
        """«Пластина под державку» без кода державки: подбирать не под что, просим код."""
        return {
            "query": q.text, "family": "insert", "groups": [], "products": [],
            "parsed": dict(q.attrs), "chips": self._chips(q, "insert"),
            "level": "уточните державку", "total_found": 0, "relaxations": [],
            "follow_ups": [
                "Укажите код державки, для которой нужна пластина (например MCLNR2525M12)."
            ],
            "note": "Для подбора пластины нужен код державки.",
        }

    def _search_compat(self, q: Query, limit: int, in_stock_only: bool) -> Dict[str, Any]:
        """Запрос без группы, но с кодом пластины: показать совместимый инструмент."""
        groups, products, total = [], [], 0
        for fam in ("holder", "mill"):
            if not self.by_family.get(fam):
                continue
            res = self._search_family(q, fam, limit, in_stock_only)
            if res["products"]:
                groups.append({"family": fam, "title": FAMILY_TITLES.get(fam, fam),
                               "products": res["products"], "total_found": res["total_found"],
                               "level": res["level"]})
                products.extend(res["products"])
                total += res["total_found"]
        out = {
            "query": q.text, "family": None, "groups": groups, "products": products[:limit],
            "parsed": dict(q.attrs), "chips": self._chips(q, None),
            "level": "подбор" if products else "нет совместимых",
            "total_found": total, "relaxations": [],
            "follow_ups": [] if products else [
                f"Под пластину {q.compat_insert} совместимых державок и корпусов фрез в каталоге не нашлось."
            ],
            "note": f"Показан инструмент, совместимый с пластиной {q.compat_insert}.",
        }
        if q.compat_insert:
            out["compatible_insert"] = q.compat_insert
        return out

    def _search_ambiguous(self, q: Query, limit: int, in_stock_only: bool) -> Dict[str, Any]:
        if not (q.free_tokens or q.insert_code or q.holder_code or q.attrs or q.compat_insert):
            return {
                "query": q.text, "family": None, "groups": [], "products": [],
                "parsed": {}, "chips": [], "level": "уточните группу",
                "total_found": 0, "relaxations": [],
                "follow_ups": ["Укажите группу товара и параметры: например «сверло 8,5 мм» или «CNMG 120408»."],
            }
        groups = []
        for fam in ("insert", "drill", "mill", "tap", "holder", "reamer", "countersink", "accessory"):
            if not self.by_family.get(fam):
                continue
            res = self._search_family(q, fam, 3, in_stock_only)
            if res["products"]:
                groups.append({"family": fam, "title": FAMILY_TITLES.get(fam, fam), "products": res["products"],
                               "total_found": res["total_found"], "level": res["level"]})
        groups.sort(key=lambda g: -g["total_found"])
        products = [p for g in groups for p in g["products"]][:limit]
        return {
            "query": q.text, "family": None, "groups": groups[:4], "products": products,
            "parsed": q.attrs, "chips": self._chips(q, None), "level": "уточните группу",
            "total_found": sum(g["total_found"] for g in groups[:4]), "relaxations": [],
            "follow_ups": ["Уточните группу товара: пластина, сверло, фреза, метчик, державка."],
            "note": "Запрос без явной группы — показаны лучшие совпадения по разным группам.",
        }

    @staticmethod
    def _pinned_match(value: Any, want: str) -> bool:
        """Артикул из ответа технолога совпадает с началом названия/артикула позиции."""
        v = compact(str(value or ""))
        w = compact(str(want or ""))
        if not v or not w:
            return False
        if v == w:
            return True
        # «BT40-SL20-10» не должен цеплять «BT40-SL20-100»
        return v.startswith(w) and not v[len(w):len(w) + 1].isdigit()

    def _search_pinned(self, q: Query, names: Sequence[str], limit: int,
                       in_stock_only: bool) -> Optional[Dict[str, Any]]:
        """Ответ технолога из таблицы обучения: показываем именно названные позиции."""
        pool, seen = [], set()
        for fam_pool in self.by_family.values():
            for it in fam_pool:
                key = it.get("id") or id(it)
                if key in seen:
                    continue
                if any(self._pinned_match(it.get("name"), n) or self._pinned_match(it.get("sku"), n)
                       for n in names):
                    pool.append(it)
                    seen.add(key)
        if not pool:
            return None
        results = self._collect(pool, q, [], [], False, q.family or "")
        # ответ технолога показываем целиком: позиции «под заказ» идут после складских
        with_stock = [r for r in results if (r[0].get("stock") or 0) > 0]
        without = [r for r in results if (r[0].get("stock") or 0) <= 0]
        results = with_stock + without
        availability = ""
        if in_stock_only and results and not with_stock:
            availability = "нет в наличии — показаны позиции под заказ"
        elif in_stock_only and without:
            availability = "часть позиций под заказ"
        fam = q.family or (pool[0].get("family") if pool else None)
        cards = [self._card(it, score, q) for it, score in results]
        # после названных технологом позиций — обычная выдача по запросу, без дублей
        extra = (self._search_family(q, q.family, limit, in_stock_only) if q.family
                 else self._search_ambiguous(q, limit, in_stock_only))
        have = {compact(p.get("sku")) + compact(p.get("name")) for p in cards}
        added = []
        for p in extra.get("products") or []:
            key = compact(p.get("sku")) + compact(p.get("name"))
            if key in have:
                continue
            have.add(key)
            added.append(p)
        cards = (cards + added)[:limit]
        out = {
            "query": q.text, "family": fam, "groups": [],
            "products": cards,
            "parsed": dict(q.attrs), "chips": self._chips(q, fam), "level": "точное",
            "total_found": len(results) + len(added), "relaxations": [], "follow_ups": [],
            "category_hints": list(q.category_hints), "trained": True,
        }
        if availability:
            out["availability"] = availability
        return out

    def _search_family(self, q: Query, fam: str, limit: int, in_stock_only: bool) -> Dict[str, Any]:
        pool = self.by_family.get(fam, [])
        if not pool:
            pool = self._related_pool(fam)
        # S2: сужаем пул через индекс кодов, когда задан точный код (O(совпадений) вместо линейного скана)
        code_for_index = q.insert_code or q.holder_code
        if code_for_index:
            want = compact(code_for_index)
            if want:
                idxs = self._by_family_and_code.get((fam, want))
                if idxs:
                    indexed_pool = [self.items[i] for i in idxs]
                    if indexed_pool:
                        pool = indexed_pool
        filters = self._filters(q, fam)
        hard = [(n, f) for n, is_hard, f in filters if is_hard]
        soft = [(n, f) for n, is_hard, f in filters if not is_hard]

        relaxed: List[str] = []
        availability = ""
        results = self._collect(pool, q, hard, soft, in_stock_only, fam)
        if not results and in_stock_only and filters:
            # точное совпадение есть, но не в наличии — показываем под заказ, а не «похожее»
            results = self._collect(pool, q, hard, soft, False, fam)
            if results:
                availability = "нет в наличии — показаны позиции под заказ"
        nearest = []
        if not results and fam == "mill" and q.compat_insert and q.attrs.get("diameter_mm"):
            # для корпусов под пластину ближайший диаметр полезнее, чем ослабление совместимости
            guard = [f for n, f in hard if n != "диаметр"] + [f for n, f in soft]
            nearest = self._nearest_diameter(pool, q.attrs["diameter_mm"], fam, q, limit, guard)
            if nearest:
                relaxed.append(f"точного диаметра нет — показан ближайший к {fmt_num(q.attrs['diameter_mm'])} мм")
                results = nearest
        if not results:
            active_soft = list(soft)
            active_hard = list(hard)
            for _ in range(len(soft) + len(hard)):
                if active_soft:
                    name, _ = active_soft.pop()
                    relaxed.append(f"ослаблен фильтр «{name}»")
                elif active_hard and len(active_hard) > 1:
                    name, _ = active_hard.pop()
                    relaxed.append(f"ослаблен фильтр «{name}»")
                else:
                    break
                results = self._collect(pool, q, active_hard, active_soft, in_stock_only, fam)
                if not results and in_stock_only:
                    results = self._collect(pool, q, active_hard, active_soft, False, fam)
                    if results:
                        availability = "нет в наличии — показаны позиции под заказ"
                if results:
                    break

        # B3: fuzzy-код по цифровому хвосту (Дамерау <= 1) при нулевом точном совпадении
        fuzzy_code = False
        if not results and q.insert_code and fam == "insert":
            want = compact(q.insert_code)
            pref = want[:4]
            digits = want[4:]
            if len(digits) >= 4:
                candidates = []
                for (f, code), idxs in self._by_family_and_code.items():
                    if f != fam or not code.startswith(pref):
                        continue
                    if abs(len(code) - len(want)) > 1:
                        continue
                    if damerau(digits, code[4:], 1) <= 1:
                        for i in idxs:
                            candidates.append(self.items[i])
                if candidates:
                    # мягкие фильтры без жёсткого кода (код уже неточный)
                    results = self._collect(candidates, q, [], soft, in_stock_only, fam)
                    if results:
                        fuzzy_code = True
                        relaxed.append(f"код не найден точно — ближайший по цифровому хвосту к {want}")

        code_level = 0
        if q.insert_code or q.holder_code:
            code_level = max((self._code_match(it, q.insert_code or q.holder_code or "")[0] for it, _ in results), default=0)
        if not results and fam in ("drill", "mill", "reamer", "countersink", "saw") and q.attrs.get("diameter_mm"):
            nearest = self._nearest_diameter(pool, q.attrs["diameter_mm"], fam, q, limit)
            if nearest:
                relaxed.append(f"точного диаметра нет — показаны ближайшие к {fmt_num(q.attrs['diameter_mm'])} мм")
                results = nearest

        level = "точное"
        if fuzzy_code:
            level = "аналог"
        elif nearest:
            level = "аналог"
        elif relaxed or 0 < code_level < 3:
            level = "частичное"
        if q.attrs.get("tap_drill_for"):
            relaxed.append(f"под резьбу {q.attrs['tap_drill_for']} диаметр сверла {fmt_num(q.attrs.get('diameter_mm'))} мм")

        products = [self._card(it, score, q) for it, score in results[:limit]]
        tap_drill = tap_drill_for(q.thread) if fam == "drill" else None
        follow = self._follow_ups(q, fam, products)
        out = {
            "query": q.text, "family": fam, "groups": [], "products": products,
            "parsed": dict(q.attrs), "chips": self._chips(q, fam), "level": level,
            "total_found": len(results), "relaxations": relaxed, "follow_ups": follow,
            "category_hints": list(q.category_hints),
        }
        if availability:
            out["availability"] = availability
        if tap_drill:
            out["tap_drill"] = tap_drill
        if fam == "holder" and q.holder_code:
            hint = holder_insert_hint(q.holder_code)
            if hint:
                out["fits_insert"] = hint
        if q.family == "insert" and q.insert_code:
            out["insert_code"] = q.insert_code
        if q.family == "holder" and q.holder_code:
            out["holder_code"] = q.holder_code
        if q.compat_insert:
            out["compatible_insert"] = q.compat_insert
        if q.holder_compat and fam == "insert":
            out["fits_holder"] = q.holder_compat_code
        return out

    def _related_pool(self, fam: str) -> List[Dict[str, Any]]:
        if fam == "tap":
            return self.by_family.get("die", [])
        if fam == "die":
            return self.by_family.get("tap", [])
        if fam == "saw":
            return [it for it in self.by_family.get("mill", []) if it.get("category") == "saw_blade"]
        return []

    def _collect(self, pool, q: Query, hard, soft, in_stock_only: bool, fam: str):
        out = []
        tokens = q.free_tokens
        for it in pool:
            if in_stock_only and it.get("stock", 0) <= 0:
                continue
            if not it.get("active", True) and it.get("stock", 0) <= 0:
                continue
            if not all(f(it) for _, f in hard):
                continue
            if not all(f(it) for _, f in soft):
                continue
            text_score = self._text_score(it, tokens)
            code_lvl = 0
            if q.insert_code or q.holder_code:
                code_lvl = self._code_match(it, q.insert_code or q.holder_code or "")[0]
            score = 0.0
            if code_lvl == 3:
                score += 120
            elif code_lvl == 2:
                score += 95
            elif code_lvl == 1:
                score += 80
            elif hard:
                score += 60
            else:
                score += 40
            score += 3.0 * text_score
            if tokens:
                doc = it.get("_tokens") or set()
                score += 4.0 * sum(1 for t in tokens if t in doc)
            if it.get("stock", 0) > 0:
                score += 5
            if not it.get("price_on_request"):
                score += 2
            if it.get("active", True):
                score += 1
            score += min(it.get("stock", 0), 200) / 200.0
            out.append((it, score))
        out.sort(key=lambda x: (-x[1], -x[0].get("stock", 0)))
        # склейка полных дублей по бренду и артикулу
        seen, uniq = set(), []
        for it, score in out:
            key = (it.get("_brand_norm"), compact(it.get("sku") or it.get("name")))
            if key in seen:
                continue
            seen.add(key)
            uniq.append((it, score))
        # порядок в ответе: при точном коде — бренд по приоритету, иначе — по релевантности (score),
        # бренд и остаток — только тай-брейки (B8).
        has_exact = any(s >= 120 for _, s in uniq)
        if has_exact:
            uniq.sort(key=lambda x: (_BRAND_RANK.get(x[0].get("_brand_norm") or "", len(_BRAND_RANK)),
                                     -(x[0].get("stock") or 0), -x[1]))
        else:
            # без точного кода — бренд по приоритету, затем остаток, затем score (B8)
            uniq.sort(key=lambda x: (_BRAND_RANK.get(x[0].get("_brand_norm") or "", len(_BRAND_RANK)),
                                     -(x[0].get("stock") or 0), -x[1]))
        return uniq

    def _nearest_diameter(self, pool, want: float, fam: str, q: Query, limit: int, guard=None):
        cands = []
        for it in pool:
            d = (it.get("attrs") or {}).get("diameter_mm")
            if d is None:
                continue
            if it.get("stock", 0) <= 0:
                continue
            if guard and not all(f(it) for f in guard):
                continue
            cands.append((abs(float(d) - want), it))
        if not cands:
            return []
        cands.sort(key=lambda x: (x[0], -x[1].get("stock", 0)))
        best_diff = cands[0][0]
        return [(it, 30 - diff) for diff, it in cands if diff <= best_diff + 1e-9][:limit]

    # ---- карточка и подсказки --------------------------------------------------------------------
    def _card(self, it: Dict[str, Any], score: float, q: Query) -> Dict[str, Any]:
        attrs = it.get("attrs") or {}
        price = it.get("price", 0.0)
        por = bool(it.get("price_on_request"))
        url = it.get("url") or ""
        return {
            "sku": it.get("sku", ""),
            "code_1c": it.get("id", ""),
            "name": it.get("name", ""),
            "brand": it.get("brand", ""),
            "category": it.get("category", ""),
            "family": it.get("family", ""),
            "grade": attrs.get("grade", ""),
            "iso_group": attrs.get("iso_group", ""),
            "stock": it.get("stock", 0),
            "price": price,
            "currency": it.get("currency", "RUB"),
            "price_on_request": por,
            "price_display": rates.price_display(price, it.get("currency", "RUB"), por),
            "source_site": "qtool.ru",
            "qtool_url": url,
            "shop_links_markdown": f"[Открыть на qtool.ru]({url})" if url else "",
            "attrs": {k: v for k, v in attrs.items() if v not in (None, "", [])},
            "score": round(score, 2),
        }

    def _chips(self, q: Query, fam: Optional[str]) -> List[str]:
        chips = []
        if fam:
            chips.append(f"группа: {FAMILY_TITLES.get(fam, fam)}")
        for cat in q.category_hints:
            title = CATEGORY_TITLES.get(cat)
            if title:
                chips.append(f"тип: {title}")
        a = q.attrs
        if q.insert_code:
            if a.get("insert_prefix"):
                chips.append(f"пластина: {a['insert_prefix']} {a.get('size_code', '')}".strip())
            else:
                chips.append(f"код: {q.insert_code}")
        if q.holder_code and not (fam == "insert" and q.holder_compat_code):
            chips.append(f"код: {q.holder_code}")
        if q.compat_insert:
            chips.append(f"под пластину: {q.compat_insert}")
        if q.holder_compat and fam == "insert":
            chips.append(f"под державку: {q.holder_compat_code}")
        if a.get("plate_shape"):
            chips.append("форма: " + PLATE_SHAPE_TITLES.get(a["plate_shape"], a["plate_shape"]))
        if a.get("plate_size"):
            chips.append(f"размер: {a['plate_size']}")
        if a.get("hand") and fam == "holder":
            chips.append("державка: правая" if a["hand"] == "R" else "державка: левая")
        if a.get("diameter_mm") and (not q.thread or a.get("tap_drill_for")):
            chips.append(f"диаметр: {fmt_num(a['diameter_mm'])} мм")
        if q.thread:
            chips.append(f"резьба: {q.thread}")
        if a.get("teeth"):
            chips.append(f"зубьев: {a['teeth']}")
        if a.get("ld_ratio"):
            chips.append(f"длина: {a['ld_ratio']}D")
        if a.get("angle_deg"):
            chips.append(f"угол: {fmt_num(a['angle_deg'])}°")
        if a.get("shank_section"):
            sec = str(a["shank_section"])
            if "×" not in sec:
                sec = f"{sec[:2]}×{sec[2:]}"
            chips.append(f"сечение: {sec} мм")
        elif a.get("shank_mm"):
            if self._round_shank(q):
                chips.append(f"хвост: Ø{fmt_num(a['shank_mm'])} мм")
            else:
                chips.append(f"хвостовик: {fmt_num(a['shank_mm'])} мм")
        if a.get("iso_group"):
            chips.append(f"группа ISO: {a['iso_group']}")
        if a.get("operation"):
            op_txt = {"finishing": "чистовая", "semi_finishing": "получистовая", "roughing": "черновая"}.get(a["operation"], a["operation"])
            chips.append(f"обработка: {op_txt}")
        if a.get("grade"):
            chips.append(f"марка: {a['grade']}")
        if a.get("collet_series"):
            chips.append(f"серия: {a['collet_series']}")
        if a.get("jaw_series"):
            chips.append(f"серия патрона: {a['jaw_series']}-{a['jaw_size']}")
        if a.get("morse_from"):
            chips.append(f"переход: Морзе {a['morse_from']} → Морзе {a['morse_to']}")
        if a.get("with_tang"):
            chips.append("с лапкой")
        if a.get("bar_shank_mm"):
            side = fmt_num(a["bar_shank_mm"])
            chips.append(f"квадрат: {side}×{side} мм")
        if a.get("clamp_mm"):
            if "tool_holder" in q.category_hints:
                chips.append(f"под хвостовик: {fmt_num(a['clamp_mm'])} мм")
            else:
                chips.append(f"под диаметр: {fmt_num(a['clamp_mm'])} мм")
        if a.get("thickness_mm"):
            chips.append(f"толщина: {fmt_num(a['thickness_mm'])} мм")
        if a.get("coating"):
            chips.append(f"покрытие: {a['coating']}")
        if a.get("material"):
            chips.append(f"материал: {a['material']}")
        if a.get("standard"):
            chips.append(f"стандарт: {a['standard']}")
        if a.get("radius_mm"):
            chips.append(f"радиус: {fmt_num(a['radius_mm'])} мм")
        if a.get("corner_radius_mm"):
            chips.append(f"радиус: {fmt_num(a['corner_radius_mm'])} мм")
        if a.get("taper"):
            chips.append(f"конус: {a['taper']}")
        if a.get("weldon"):
            chips.append("хвостовик: Weldon")
        if a.get("tool_d_mm"):
            chips.append(f"диаметр хвоста: {fmt_num(a['tool_d_mm'])} мм")
        if a.get("tool_l_mm"):
            chips.append(f"длина: {fmt_num(a['tool_l_mm'])} мм")
        if a.get("chuck_system"):
            chips.append(f"система: {a['chuck_system']}")
        if a.get("chuck_taper"):
            chips.append(f"конус патрона: {a['chuck_taper']}")
        if a.get("slot_mm"):
            chips.append(f"паз: {a['slot_mm']} мм")
        return chips

    def _follow_ups(self, q: Query, fam: str, products: List[Dict[str, Any]]) -> List[str]:
        a = q.attrs
        tips = []
        if q.compat_requested and not q.compat_insert and not (a.get("plate_shape") and a.get("plate_size")):
            tips.append("Укажите код пластины, под которую нужен инструмент (например CNMG 120408 или APMT1604).")
        if fam == "drill":
            if not a.get("diameter_mm"):
                tips.append("Укажите диаметр сверла (например «8,5 мм»).")
            if not a.get("material"):
                tips.append("Уточните материал: HSS, HSS-E (нержавейка) или твердый сплав.")
        elif fam == "mill":
            if not a.get("diameter_mm"):
                tips.append("Укажите диаметр фрезы.")
            if not a.get("teeth"):
                tips.append("Уточните число зубьев (2F, 3F, 4F).")
        elif fam in ("tap", "die"):
            if not q.thread:
                tips.append("Укажите резьбу: например М10х1,5.")
        elif fam == "holder":
            if not q.holder_code and not a.get("shank_mm"):
                if self._round_shank(q):
                    tips.append("Укажите диаметр хвоста (16, 20, 25 мм) или код державки.")
                else:
                    tips.append("Укажите сечение державки (16х16, 20х20, 25х25) или её код.")
            elif not products and self._round_shank(q):
                # шанк распарсан, но подходящих державок не нашлось — предлагают уточнить диаметр
                tips.append("Укажите диаметр хвоста (16, 20, 25 мм) или код державки.")
        elif fam == "insert":
            if not q.insert_code and not q.holder_compat and not (a.get("plate_shape") or a.get("plate_size")):
                tips.append("Укажите код пластины (например CNMG 120408) или форму и размер.")
        elif fam == "accessory":
            if "tool_holder" in q.category_hints and not a.get("clamp_mm"):
                tips.append("Укажите диаметр хвостовика инструмента (16, 20, 25, 32 мм).")
        return tips[:3]


FAMILY_TITLES = {
    "insert": "пластины",
    "drill": "сверла",
    "mill": "фрезы",
    "tap": "метчики",
    "die": "плашки",
    "reamer": "развертки",
    "countersink": "зенковки и фаскосниматели",
    "holder": "державки и резцы",
    "accessory": "оснастка и крепеж",
    "measuring": "измерительный инструмент",
    "saw": "пилы и диски",
}
