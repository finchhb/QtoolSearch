"""
src/xlsx_reader.py - чтение .xlsx на стандартной библиотеке (zipfile + ElementTree).

Отличия от build_catalog._read_xlsx_rows_pure_python:
- читает ВСЕ листы книги (а не только первый);
- ширина строки динамическая: колонки не обрезаются по max_cols, хвост таблицы не теряется;
- умеет находить строку заголовка и строить индекс колонок по коду Битрикса [ATT_...]
  (переименование русского заголовка не ломает приём данных);
- возвращает имя листа, чтобы отчёт качества был привязан к источнику.
"""
import hashlib
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

_COL_CACHE: Dict[str, int] = {}


def _col_index(ref: str) -> int:
    letters = ""
    for ch in ref:
        if not ("A" <= ch <= "Z"):
            break
        letters += ch
    if not letters:
        return -1
    idx = _COL_CACHE.get(letters)
    if idx is None:
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch) - 64)
        idx -= 1
        _COL_CACHE[letters] = idx
    return idx


def _text_of(elem) -> str:
    return "".join(t.text or "" for t in elem.iter() if t.tag.endswith("}t"))


@dataclass
class Sheet:
    name: str
    rows: List[List[str]] = field(default_factory=list)


def _sheet_targets(zf: zipfile.ZipFile) -> List[tuple]:
    """[(имя листа, путь внутри архива)] в порядке книги."""
    try:
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        rels = None
    rel_map = {}
    if rels is not None:
        for rel in rels:
            rel_map[rel.attrib.get("Id")] = rel.attrib.get("Target", "")
    out = []
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
    except (KeyError, ET.ParseError):
        return out
    for sheet in wb.iter():
        if not sheet.tag.endswith("}sheet"):
            continue
        name = sheet.attrib.get("name", "")
        target = rel_map.get(sheet.attrib.get(_NS_REL), "")
        target = target.lstrip("/")
        if target and not target.startswith("xl/"):
            target = "xl/" + target
        if not target:
            continue
        out.append((name, target))
    return out


def read_workbook(path: str) -> List[Sheet]:
    """Все листы книги. Пустые строки пропускаются, значения обрезаются по краям."""
    with zipfile.ZipFile(path, "r") as zf:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            with zf.open("xl/sharedStrings.xml") as f:
                for _, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag.endswith("}si"):
                        shared.append(_text_of(elem))
                        elem.clear()

        targets = _sheet_targets(zf)
        if not targets:
            targets = [(f"sheet{i}", n) for i, n in enumerate(
                sorted(x for x in zf.namelist() if x.startswith("xl/worksheets/sheet") and x.endswith(".xml")), 1)]

        sheets = []
        for name, target in targets:
            if target not in zf.namelist():
                continue
            rows: List[List[str]] = []
            with zf.open(target) as f:
                cur: List[str] = []
                for event, elem in ET.iterparse(f, events=("start", "end")):
                    tag = elem.tag
                    if event == "start" and tag.endswith("}row"):
                        cur = []
                    elif event == "end" and tag.endswith("}c"):
                        idx = _col_index(elem.attrib.get("r", ""))
                        if idx < 0:
                            idx = len(cur)
                        ctype = elem.attrib.get("t", "")
                        if ctype == "inlineStr":
                            val = _text_of(elem)
                        else:
                            val = ""
                            for child in elem:
                                if child.tag.endswith("}v") and child.text is not None:
                                    if ctype == "s":
                                        try:
                                            val = shared[int(child.text)]
                                        except (ValueError, IndexError):
                                            val = ""
                                    else:
                                        val = child.text
                                    break
                        val = (val or "").strip()
                        if idx >= len(cur):
                            cur.extend([""] * (idx + 1 - len(cur)))
                        cur[idx] = val
                    elif event == "end" and tag.endswith("}row"):
                        if any(cur):
                            rows.append(cur)
                        elem.clear()
            sheets.append(Sheet(name=name, rows=rows))
        return sheets


CODE_RE = re.compile(r"\[([A-Z0-9_]{2,})\]")


def header_code(raw: str) -> str:
    """Код колонки: [ATT_RAZMER_US_PLASTINI] -> ATT_RAZMER_US_PLASTINI, иначе нормализованный текст."""
    s = (raw or "").strip()
    m = CODE_RE.search(s.upper())
    if m:
        return m.group(1)
    return re.sub(r"\s+", " ", s.lower())


def header_index(headers: Sequence[str]) -> Dict[str, int]:
    idx: Dict[str, int] = {}
    for i, h in enumerate(headers):
        if not (h or "").strip():
            continue
        idx.setdefault(header_code(h), i)
        idx.setdefault(re.sub(r"\s+", " ", h.strip().lower()), i)
    return idx


def schema_hash(headers: Sequence[str]) -> str:
    return hashlib.sha1("|".join(header_code(h) for h in headers if h and h.strip()).encode("utf-8")).hexdigest()[:12]


def find_header_row(rows: Sequence[Sequence[str]], required_any: Sequence[str], scan: int = 15) -> Optional[int]:
    """Индекс строки заголовка: первая строка из первых `scan`, где есть хотя бы `required_any` кодов."""
    want = {header_code(w).lower() for w in required_any}
    for i, row in enumerate(rows[:scan]):
        codes = {header_code(c).lower() for c in row if c and c.strip()}
        if codes & want:
            return i
    return None
