"""Нормализация букв в кодах инструмента: омоглифы, раскладка, кириллица по буквам.

Общий модуль для catalog_search (коды пластин и державок в запросе) и iso5608 (коды
оснастки из каталога): без него между ними возник бы циклический импорт.
"""
import re
from typing import List

_RU_TO_EN = {
    "й": "q", "ц": "w", "у": "e", "к": "r", "е": "t", "н": "y", "г": "u", "ш": "i", "щ": "o", "з": "p",
    "х": "[", "ъ": "]", "ф": "a", "ы": "s", "в": "d", "а": "f", "п": "g", "р": "h", "о": "j", "л": "k",
    "д": "l", "ж": ";", "э": "'", "я": "z", "ч": "x", "с": "c", "м": "v", "и": "b", "т": "n", "ь": "m",
    "б": ",", "ю": ".",
}
_HOMOGLYPHS = {
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "У": "Y", "Х": "X",
}
_RU_CODE_LETTERS = {
    "а": "a", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "j",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "c", "т": "t",
    "у": "y", "ф": "f", "х": "x", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y",
    "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def layout_to_latin(s: str) -> str:
    return "".join(_RU_TO_EN.get(ch, ch) for ch in (s or "").lower())


def homoglyph_latin(s: str) -> str:
    return "".join(_HOMOGLYPHS.get(ch, ch) for ch in (s or ""))


def cyrillic_code_letters(s: str) -> str:
    """Кириллица по буквам кода: «РПМТ» -> RPMT (регистр сохраняется)."""
    out = []
    for ch in s or "":
        low = ch.lower()
        if low in _RU_CODE_LETTERS:
            tr = _RU_CODE_LETTERS[low]
            out.append(tr.upper() if ch.isupper() else tr)
        else:
            out.append(ch)
    return "".join(out)


def code_variants(s: str) -> List[str]:
    """Варианты записи кода: омоглифы, как есть, кириллица по буквам, раскладка.

    Омоглифы идут первыми: в смешанной записи «MCВNR» кириллическая «В» - это
    латинская B, а не V из русского названия буквы. Полностью кириллический код
    омоглифами не собирается и доходит до побуквенной транслитерации.
    """
    base = (s or "").strip()
    out: List[str] = []
    for v in (homoglyph_latin(base), base, cyrillic_code_letters(base), layout_to_latin(base)):
        if v and v not in out:
            out.append(v)
    return out


def normalize_separators(s: str) -> str:
    """Пробелы и тире -> «-», повторные дефисы схлопываются."""
    out = re.sub(r"[\s\u2013\u2014]+", "-", (s or "").strip())
    return re.sub(r"-{2,}", "-", out).strip("-")
