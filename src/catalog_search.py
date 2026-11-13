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
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src import rates
from src.code_normalize import cyrillic_code_letters, homoglyph_latin, layout_to_latin
from src.iso5608 import parse_holder_code
from src.site_catalog import _RE_DIA, _RE_MM, _dims, extract_common, extract_teeth, extract_thread

# --------------------------------------------------------------------------------------------------
# Нормализация
# --------------------------------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-zа-я0-9]+(?:[.,/][a-zа-я0-9]+)*")

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
    return None


def operation_from_text(text: str) -> Optional[str]:
    low = (text or "").lower().replace("ё", "е")
    for pattern, op in _OP_RX:
        if re.search(pattern, low):
            return op
    return None


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9а-я]", "", (s or "").lower())


def fmt_num(value: Any) -> str:
    """Число для показа: 8.5 -> «8,5», 90.0 -> «90»."""
    if isinstance(value, float):
        return f"{value:g}".replace(".", ",")
    return str(value)


def query_variants(q: str) -> List[str]:
    """Варианты написания кода: как есть, омоглифы, неверная раскладка, кириллица по буквам кода."""
    base = (q or "").lower().replace("ё", "е")
    out = [base, homoglyph_latin(base), cyrillic_code_letters(base), layout_to_latin(base)]
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
    return re.sub(r"(?<=\d)[lI|](?=\d)", "1", s)


_HOLDER_PREFIXES = {
    "PCLN", "MCLN", "PWLN", "MWLN", "PTGN", "MTGN", "PDJN", "MDJN", "MVJN", "PVJN",
    "PSSN", "MSSN", "SCLC", "SDJC", "STGC", "SVJB", "SVJC", "SDUC",
}
_INSERT_SHAPES = set("ABCDEHKLMOPRSTVW")

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


def insert_code_from_text(text: str) -> Optional[str]:
    """CNMG 12 04 08 / CNMG120408 -> CNMG120408. Хвост из букв (стружколом) не приклеиваем."""
    src = cyrillic_code_letters((text or "").lower().replace("ё", "е")).upper()
    toks = re.findall(r"[A-Z0-9]+", _fix_digit_letters(src))
    for i, tok in enumerate(toks):
        if re.fullmatch(r"[A-Z]{2,5}\d{4,6}[A-Z]{0,4}", tok):
            # MTJNR2525 пишется как 5 букв + 4 цифры, но это код державки, а не пластины.
            if tok[0] in _INSERT_SHAPES and not parse_holder_code(tok):
                return tok
            continue
        if re.fullmatch(r"[A-Z]{2,5}", tok):
            if tok[0] not in _INSERT_SHAPES or tok[:4] in _HOLDER_PREFIXES:
                continue  # не пластина (оснастка или транслитерированное слово)
            digits = ""
            j = i + 1
            while j < len(toks) and re.fullmatch(r"\d{1,6}", toks[j]) and len(digits) < 6:
                digits += toks[j]
                j += 1
            if 4 <= len(digits) <= 6:
                code = tok + digits
                if not parse_holder_code(code):
                    return code
    return None


def holder_code_from_text(text: str) -> Optional[str]:
    """PCLNR 2525 M12 / SNR0006K06-A12 -> компактный код с сохранением дефиса.

    Берём только токены, которые целиком состоят из латиницы (омоглифы допускаются):
    «державка» после транслитерации иначе приклеивалась бы к коду.
    """
    toks = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", text or "")
    for i, tok in enumerate(toks):
        letters = homoglyph_latin(tok)
        if any(ch.isalpha() and not ("A" <= ch.upper() <= "Z") for ch in letters):
            continue
        cand = letters.upper()
        if re.fullmatch(r"[A-Z]{1,6}\d{2,5}[A-Z]?\d{0,4}(?:-[A-Z0-9]{1,10})?", cand):
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
            if re.fullmatch(r"\d{2,5}[A-Z]?\d{0,4}", digits):
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
    ("accessory", r"цанг|патрон|винт|гайк|ключ|сож|тиск|кулачк|адаптер|переходник|втулк"),
    ("measuring", r"штанген|микрометр|нутромер|линейк|угломер|индикатор|рулетк"),
    ("saw", r"пил[аы]|пильн|дисков.*пил"),
]

CATEGORY_HINTS = {
    "drill": [
        ("center_drill", r"центровоч|центровк"),
        ("crown_drill", r"корончат"),
        ("drill_head", r"головк"),
        ("drill_body", r"корпус.*головк|под головк"),
        ("indexable_drill_body", r"корпусн|сменн.*пластин|под пластину"),
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
}

HOLDER_CATEGORY_TITLES = {
    "holder_internal": "расточная",
    "holder_external": "наружная",
    "holder_grooving": "канавочная",
    "holder_threading": "резьбовая",
}


class Query:
    def __init__(self, text: str, insert_prefixes: Optional[set] = None):
        self.text = (text or "").strip()
        self.low = self.text.lower().replace("ё", "е")
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
        self.compat_requested = False
        self.holder_compat: Optional[Dict[str, Any]] = None
        self.holder_compat_code: Optional[str] = None
        self.holder_compat_requested = False
        self._insert_prefixes = insert_prefixes or set()
        self._parse()

    def _parse(self) -> None:
        low = self.low
        # «державка 2525 под CNMG1204», «фреза 120 под APMT» — код после «под» задаёт
        # совместимую пластину, а группа определяется по основному слову запроса.
        code_text = self.text
        under = self._parse_compat_insert()
        if under:
            code_text = (self.text[:under[0]] + " " + self.text[under[1]:]).strip()
        elif _RE_COMPAT_PHRASE.search(code_text):
            # «фреза под пластину» без кода: фраза не должна уводить запрос в группу пластин
            code_text = _RE_COMPAT_PHRASE.sub(" ", code_text).strip()
        if under or _RE_COMPAT_PHRASE.search(self.text):
            self.compat_requested = True
        low = code_text.lower().replace("ё", "е")
        for fam, pattern in FAMILY_KEYWORDS:
            if re.search(pattern, low):
                self.family = fam
                break
        for cat, pattern in CATEGORY_HINTS.get(self.family or "", []):
            if re.search(pattern, low):
                self.category_hints.append(cat)

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
                code = insert_code_from_text(v)
                if code and not compact(rev_holder or "").startswith(compact(code)):
                    self.insert_code = code
                    self.family = "insert"
                    break
        if self.family in (None, "holder"):
            # без варианта «неверная раскладка»: русские слова превращаются в латинский
            # набор, который иначе склеивается с сечением в ложный код державки
            for v in query_variants(code_text)[:3]:
                code = holder_code_from_text(v)
                if code:
                    self.holder_code = code
                    if self.family is None:
                        self.family = "holder"
                    break

        # «пластина под державку» без кода: подбирать не под что, просим код державки.
        if self.family == "insert" and not self.insert_code and _RE_HOLDER_MENTION.search(self.text):
            self.holder_compat_requested = True

        if self.family == "insert":
            up = self.text.upper().replace("Ё", "Е")
            g = re.search(r"(?<![\w.])(\d{4}|[A-Z]{1,3}\d{3,4})(?![\w.])", up)
            if g and not (self.insert_code and g.group(1) in self.insert_code) and not self.holder_compat_requested:
                self.attrs["grade"] = g.group(1)
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

        b = re.search(r"(?:бренд|марка|производител[ья])\s*[:—-]?\s*([a-zа-я0-9-]{2,20})", low)
        if b:
            self.brand = b.group(1)

        common = extract_common(low)
        # В коде державки «M16» - размер пластины, а не метрическая резьба.
        thread = None if self.family == "holder" else extract_thread(self.text)
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
        if m:
            val = float(m.group(1).replace(",", "."))
            if 1 <= val <= 200:
                self.attrs["shank_mm"] = val

        dims = _dims(self.text)
        if self.family == "holder" and "shank_mm" not in self.attrs:
            sec = re.search(r"(?<!\d)(\d{2})(\d{2})(?!\d)", code_text)
            if sec and sec.group(1) == sec.group(2) and 8 <= int(sec.group(1)) <= 50:
                self.attrs["shank_mm"] = float(sec.group(1))
                self.attrs["shank_section"] = sec.group(0)
        if dims and self.family == "holder" and "shank_mm" not in self.attrs:
            self.attrs["shank_mm"] = dims[0]

        m = re.search(r"(?:h8|h7|h9|h6)\b", low)
        if m and self.family == "reamer":
            self.attrs["tolerance"] = m.group(0).upper()

        m = re.search(r"(?:er|er-)\s?(\d{1,2})", low)
        if m and self.family == "accessory":
            self.attrs["collet_series"] = f"ER{m.group(1)}"
            clamp = re.search(r"(?:er-?\d{1,2})\D{0,4}(\d{1,2}(?:[.,]\d)?)\s*(?:мм)?\b", low)
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
        self.free_tokens = [t for t in tokenize(self.text) if t not in stop and len(t) > 1 and not re.fullmatch(r"\d+[.,]?\d*", t)]
        if self.compat_insert:
            self.free_tokens = [t for t in self.free_tokens if t != self.compat_insert.lower()]
        if self.holder_compat_code:
            hc = compact(self.holder_compat_code)
            self.free_tokens = [t for t in self.free_tokens if compact(t) not in hc]

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
_RE_HOLDER_MENTION = re.compile(r"\bдержавк[а-яё]*\b", re.I)
_RE_PAREN_INSERT = re.compile(r"\(([A-Z]{2,5}\d{2,4})")
# Названия групп словами. Короткие уточнения в диалоге («12», «под CNMG12», «чистовая»)
# группу не называют — их надо дополнять предыдущим запросом.
_RE_FAMILY_TOPIC = re.compile(
    r"\b(?:пластин|сверл|фрез|борфрез|метчик|раскатник|плашк|разверт|зенков|зенкер|"
    r"фаскосним|гратосним|державк|борштанг|резец|резц|минирез|оправк|расточн|"
    r"цанг|патрон|винт|гайк|ключ|пил)", re.I
)


def is_self_contained_query(text: str) -> bool:
    """«метчик M10», «державка 2020 под CNMG12», «mcbnr 2020» — новый запрос, а не уточнение.

    Уточнения («12», «под CNMG12», «чистовая», «под пластину DNMG15») группу и код не задают.
    """
    topic = _RE_UNDER_INSERT.sub(" ", text or "")
    if _RE_FAMILY_TOPIC.search(topic.lower()):
        return True
    q = Query(topic)
    # «M10» даёт holder_code, но это размер резьбы в уточнении, а не код оснастки
    return bool(q.insert_code or (q.holder_code and parse_holder_code(q.holder_code)))


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
        for it in self.items:
            attrs = it.get("attrs") or {}
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
            text = " ".join(str(x) for x in (
                it.get("sku"), it.get("name"), it.get("brand"), it.get("category"),
                attrs.get("iso_code"), attrs.get("holder_code"), attrs.get("grade"),
                attrs.get("thread"), attrs.get("coating"), attrs.get("standard"),
            ) if x)
            toks = set(tokenize(text))
            it["_tokens"] = toks
            it["_compact"] = compact(f"{it.get('sku')} {it.get('name')}")
            code_src = " ".join(str(x) for x in (it.get("sku"), attrs.get("iso_code"), attrs.get("holder_code")) if x)
            it["_code_compact"] = compact(code_src)
            it["_brand_norm"] = compact(it.get("brand", ""))
            doc_tokens.append(toks)
            for t in toks:
                df[t] = df.get(t, 0) + 1
                if len(t) >= 4 and any(ch.isdigit() for ch in t):
                    vocab.add(t)
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
                out.append(("код", True, lambda it: self._code_match(it, q.insert_code)[0] > 0))
            if q.holder_compat:
                out.append(("под державку", True, lambda it: self._insert_fits_holder(it, q)))
            if a.get("size_code"):
                out.append(("размер", True, lambda it: str((it["attrs"] or {}).get("size_code") or "").zfill(2) == str(a["size_code"]).zfill(2)))
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
                out.append(("марка", False, lambda it: (
                    compact(str(it["attrs"].get("grade") or "")) == want_grade
                    or want_grade in compact(str(it.get("name") or ""))
                )))
        elif fam in ("drill", "mill", "reamer"):
            if fam == "mill" and q.compat_insert:
                out.append(("под пластину", True, lambda it: self._mill_fits(it, q)))
            if a.get("diameter_mm"):
                tol = 0.06 if a["diameter_mm"] < 10 else 0.11
                out.append(("диаметр", True, lambda it: self._near(it["attrs"].get("diameter_mm"), a["diameter_mm"], tol)))
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
            if q.compat_insert:
                out.append(("под пластину", True, lambda it: self._holder_fits(it, q)))
            if q.holder_code:
                out.append(("код", True, lambda it: self._code_match(it, q.holder_code)[0] > 0))
            if a.get("shank_mm"):
                if self._round_shank(q):
                    # «расточная державка с хвостом 25»: сравниваем диаметр круглого хвоста
                    out.append(("диаметр хвоста", True, lambda it: self._near(
                        it["attrs"].get("shank_diameter_mm"), a["shank_mm"], 0.5)))
                else:
                    out.append(("сечение", True, lambda it: (
                        not it["attrs"].get("shank_diameter_mm")
                        and self._near(it["attrs"].get("shank_mm"), a["shank_mm"], 0.5))))
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
            if a.get("collet_series"):
                out.append(("серия", True, lambda it: (it["attrs"].get("collet_series") or "").upper() == a["collet_series"].upper()))
            if a.get("clamp_mm"):
                want = f"{a['clamp_mm']:g}"
                out.append(("диаметр зажима", False, lambda it: (
                    str(it["attrs"].get("clamp_range") or "").endswith("-" + want)
                    or bool(re.search(rf"(?<![\d.]){re.escape(want)}(?:[.,]0)?\s*мм", str(it.get("name") or "")))
                )))

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
        return "holder_internal" in q.category_hints

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
    def search(self, text: str, limit: int = 8, in_stock_only: bool = True) -> Dict[str, Any]:
        q = Query(text, self._insert_prefixes)
        if q.insert_code:
            q.insert_code = self._canonical_insert_code(q.insert_code)
        if q.compat_insert:
            fixed = self._canonical_insert_code(q.compat_insert)
            if fixed != q.compat_insert:
                q._set_compat(fixed)
        if q.family is None:
            if q.compat_insert:
                return self._search_compat(q, limit, in_stock_only)
            return self._search_ambiguous(q, limit, in_stock_only)
        if q.compat_requested and not q.compat_insert:
            return self._compat_ask_code(q)
        if q.holder_compat_requested and not q.holder_compat:
            return self._holder_ask_code(q)
        return self._search_family(q, q.family, limit, in_stock_only)

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

    def _search_family(self, q: Query, fam: str, limit: int, in_stock_only: bool) -> Dict[str, Any]:
        pool = self.by_family.get(fam, [])
        if not pool:
            pool = self._related_pool(fam)
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

        code_level = 0
        if q.insert_code or q.holder_code:
            code_level = max((self._code_match(it, q.insert_code or q.holder_code or "")[0] for it, _ in results), default=0)
        if not results and fam in ("drill", "mill", "reamer", "countersink", "saw") and q.attrs.get("diameter_mm"):
            nearest = self._nearest_diameter(pool, q.attrs["diameter_mm"], fam, q, limit)
            if nearest:
                relaxed.append(f"точного диаметра нет — показаны ближайшие к {fmt_num(q.attrs['diameter_mm'])} мм")
                results = nearest

        level = "точное"
        if nearest:
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
            title = HOLDER_CATEGORY_TITLES.get(cat)
            if title:
                chips.append(f"тип: {title}")
        a = q.attrs
        if q.insert_code:
            chips.append(f"код: {q.insert_code}")
        if q.holder_code and not (fam == "insert" and q.holder_compat_code):
            chips.append(f"код: {q.holder_code}")
        if q.compat_insert:
            chips.append(f"под пластину: {q.compat_insert}")
        if q.holder_compat and fam == "insert":
            chips.append(f"под державку: {q.holder_compat_code}")
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
        if a.get("clamp_mm"):
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
        return chips

    def _follow_ups(self, q: Query, fam: str, products: List[Dict[str, Any]]) -> List[str]:
        a = q.attrs
        tips = []
        if q.compat_requested and not q.compat_insert:
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
        elif fam == "insert":
            if not q.insert_code and not q.holder_compat:
                tips.append("Укажите код пластины (например CNMG 120408) или форму и размер.")
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
