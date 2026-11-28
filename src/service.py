"""
src/service.py - единое ядро QtoolSearch для всех точек входа (API, Streamlit, MAX-бот).

Зачем отдельный слой:
- движок (src.engine.ToolAdvisorEngine) инициализируется ОДИН раз и держит индексы в памяти;
- все клиенты (FastAPI, Streamlit, бот) ходят в один и тот же индекс, а не в три копии;
- потокобезопасность: инициализация и перезагрузка каталога под отдельным локом, поиск
  идёт в уже собранном индексе (движок хранит текст запроса в threading.local, индекс
  перечитывается по mtime без остановки сервера);
- здесь же живёт «очистка грязных строк» и разбор .xlsx/.csv для пакетного подбора,
  чтобы логика не дублировалась в API, виджете и боте.

Модуль на стандартной библиотеке + openpyxl (только для выгрузки .xlsx результатов).
"""
from __future__ import annotations

import csv
import io
import os
import re
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Движок читает .env сам (load_env_file в app.py); здесь .env не трогаем — клиент решает, когда грузить.
from src.engine import ToolAdvisorEngine

# Максимум строк в одном пакетном запросе (по ТЗ).
MAX_BATCH = 500
# Сколько потоков задействовать для пакетного подбора (индекс только для чтения, движок потокобезопасен).
BATCH_WORKERS = 8
# Сколько альтернатив (топ-2, топ-3) отдавать в пакетном режиме.
DEFAULT_LIMIT = 3

# Уровни совпадения движка -> понятная метка типа для API/виджета/бота.
_MATCH_LABELS = {
    "точное": "точное",
    "частичное": "близкий аналог",
    "аналог": "полный аналог",
}


def _match_label(level: Optional[str], has_products: bool) -> str:
    if not has_products:
        return "не найдено"
    return _MATCH_LABELS.get(level or "", level or "подбор")


# --------------------------------------------------------------------------------------------------
# Очистка «грязных» строк (Excel/PDF-спецификации)
# --------------------------------------------------------------------------------------------------
_LEADING_NUM = re.compile(r"^\s*\d{1,4}[.)\-–]\s+")          # «1. CNMG…», «2) …»
# Количество в хвосте строки берём ТОЛЬКО при явном маркере: «x 5», «× 5», «* 5» или с единицей «5 шт».
# Голое число в конце (например «… PM 4325») — это часть кода/марки, его не срезаем.
_QTY_MARKED = re.compile(r"(?:[xх×*]\s*|\s)(\d{1,6})\s*(?:шт\.?|pcs\.?|-?piece|уп\.?|упак\.?|компл\.?)\s*$", re.I)
_QTY_TIMES = re.compile(r"[xх×*]\s*(\d{1,6})\s*$", re.I)
_TRAILING_UNIT = re.compile(r"\s+(?:шт\.?|pcs\.?|уп\.?|упак\.?|компл\.?)\s*$", re.I)
_MULTI_SPACE = re.compile(r"\s+")


def clean_query_line(raw: Any, qty: Optional[Any] = None) -> Dict[str, Any]:
    """Приводит одну строку из списка/Excel к чистому запросу.

    - убирает нумерацию «1.», «2)», маркеры списка;
    - сжимает пробелы, срезает хвостовые единицы (шт., уп.);
    - сохраняет количество: из отдельного столбца (qty) либо из хвоста строки («… x 5»).
    Возвращает {"text": чистый запрос, "qty": количество или None}.
    """
    text = "" if raw is None else str(raw)
    text = text.replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-")
    text = _LEADING_NUM.sub("", text)
    text = _MULTI_SPACE.sub(" ", text).strip()

    parsed_qty: Optional[int] = None
    if qty is not None and str(qty).strip():
        m = re.search(r"\d+", str(qty))
        if m:
            parsed_qty = int(m.group())
    if parsed_qty is None:
        m = _QTY_MARKED.search(text) or _QTY_TIMES.search(text)
        if m:
            parsed_qty = int(m.group(1))
            text = text[: m.start()].strip(" -/,")
    text = _TRAILING_UNIT.sub("", text).strip()
    return {"text": text, "qty": parsed_qty}


def split_text_list(text: str) -> List[str]:
    """Разбивает вставленный список (столбец из Excel / многострочный текст) на строки."""
    out: List[str] = []
    for raw in re.split(r"[\n\r]+", text or ""):
        s = raw.strip()
        if s:
            out.append(s)
    return out


# --------------------------------------------------------------------------------------------------
# Чтение .xlsx / .csv для пакетного подбора
# --------------------------------------------------------------------------------------------------
# Заголовки колонок, которые обычно содержат артикул/наименование.
_ART_HINTS = ("артикул", "artic", "sku", "код", "наимен", "name", "товар", "позиц", "номенклат")


def _looks_like_article_column(values: Sequence[str]) -> int:
    """Эвристика: какая колонка похожа на артикул/наименование (по доле непустых и «кодовых» значений)."""
    best_idx, best_score = -1, -1.0
    width = max((len(r) for r in values), default=0)
    for col in range(width):
        cells = [r[col] for r in values if col < len(r) and r[col].strip()]
        if not cells:
            continue
        nonempty = len(cells) / max(len(values), 1)
        codey = sum(1 for c in cells if re.search(r"[A-Za-zА-Яа-я]{2,}\d|\d{3,}", c)) / len(cells)
        score = nonempty * 0.4 + codey * 0.6
        if score > best_score:
            best_idx, best_score = col, score
    return best_idx


def read_table_bytes(filename: str, raw: bytes) -> Tuple[List[str], List[List[str]], Optional[int]]:
    """Читает .xlsx или .csv. Возвращает (заголовки, строки, индекс колонки артикула).

    Для .xlsx используется штатный парсер проекта (zipfile+ElementTree), для .csv — csv-модуль.
    Индекс колонки артикула определяется по заголовку, иначе эвристикой по содержимому.
    """
    name = (filename or "").lower()
    rows: List[List[str]] = []
    headers: List[str] = []
    if name.endswith(".csv") or name.endswith(".txt"):
        text = raw.decode("utf-8-sig", errors="replace")
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        rows = [[(c or "").strip() for c in row] for row in reader if any((c or "").strip() for c in row)]
    else:
        from src.xlsx_reader import read_workbook
        tmp = _write_temp(raw, ".xlsx")
        try:
            sheets = read_workbook(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if sheets:
            rows = [[(c or "").strip() for c in r] for r in sheets[0].rows if any((c or "").strip() for c in r)]

    if not rows:
        return [], [], None

    # Первая строка — заголовок, если в ней есть «артикульный» намёк; иначе считаем её данными.
    first = rows[0]
    header_like = any(h in " ".join(first).lower() for h in _ART_HINTS)
    if header_like:
        headers = first
        data = rows[1:]
    else:
        headers = [f"Столбец {i + 1}" for i in range(max(len(r) for r in rows))]
        data = rows

    col = _find_article_column(headers, data)
    return headers, data, col


def _find_article_column(headers: Sequence[str], data: Sequence[Sequence[str]]) -> Optional[int]:
    low = [h.lower() for h in headers]
    for i, h in enumerate(low):
        if any(hint in h for hint in _ART_HINTS):
            return i
    if data:
        return _looks_like_article_column(data)
    return 0 if headers else None


def _write_temp(raw: bytes, suffix: str) -> str:
    import tempfile

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="qtool_up_")
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    return path


# --------------------------------------------------------------------------------------------------
# Сервис: singleton вокруг движка
# --------------------------------------------------------------------------------------------------
class SearchService:
    """Потокобезопасная обёртка над ToolAdvisorEngine (инициализация один раз)."""

    _instance: Optional["SearchService"] = None
    _inst_lock = threading.Lock()

    def __init__(self, auto_sync: Optional[bool] = None):
        self._lock = threading.RLock()
        if auto_sync is None:
            auto_sync = (
                not os.path.exists("data/catalog_qtool.csv")
                and not os.path.exists("data/catalog_rinscom.csv")
                and os.environ.get("SKIP_RINSCOM_SYNC") != "1"
            )
        self._engine = ToolAdvisorEngine(auto_sync_rinscom=auto_sync)
        self._load_custom_instructions()

    @classmethod
    def instance(cls) -> "SearchService":
        with cls._inst_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def engine(self) -> ToolAdvisorEngine:
        return self._engine

    def _load_custom_instructions(self) -> None:
        path = os.path.join("data", "custom_instructions.txt")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                if txt:
                    self._engine.set_custom_instructions(txt)
            except OSError:
                pass

    # ---- одиночный поиск ------------------------------------------------------------------------
    def search_single(self, query: str, limit: int = 5) -> Dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"query": query, "status": "empty", "parsed": {}, "corrected": "", "results": []}
        with self._lock:
            res = self._engine.process_query(q)
        return self._shape_single(q, res, limit)

    def _shape_single(self, query: str, res: Dict[str, Any], limit: int) -> Dict[str, Any]:
        tr = res.get("tool_result") or {}
        products = tr.get("products") or []
        level = tr.get("level")
        results = [self._card(p, level, products, idx) for idx, p in enumerate(products[:limit])]
        status = "ok" if results else "not_found"
        return {
            "query": query,
            "status": status,
            "parsed": res.get("parsed") or {},
            "corrected": self._corrected(res),
            "chips": tr.get("chips") or [],
            "level": level,
            "total_found": tr.get("total_found") or len(products),
            "response_text": res.get("response_text", ""),
            "results": results,
        }

    @staticmethod
    def _corrected(res: Dict[str, Any]) -> str:
        parsed = res.get("parsed") or {}
        code = parsed.get("code") or ""
        return code

    def _card(self, p: Dict[str, Any], level: Optional[str], all_products: Sequence[Dict[str, Any]], idx: int) -> Dict[str, Any]:
        has = bool(p)
        # Первая позиция при точном уровне — точное совпадение; остальные — аналоги.
        if idx == 0:
            label = _match_label(level, has)
        else:
            label = "полный аналог" if (level or "") == "точное" else _match_label(level, has)
        return {
            "sku": p.get("sku", ""),
            "name": p.get("name", ""),
            "brand": p.get("brand", ""),
            "grade": p.get("grade", ""),
            "iso_group": p.get("iso_group", ""),
            "stock": int(p.get("stock") or 0),
            "price_display": p.get("price_display") or ("по запросу" if p.get("price_on_request") else ""),
            "price_on_request": bool(p.get("price_on_request")),
            "url": p.get("qtool_url", ""),
            "match_type": label,
            "match_level": level,
            "attrs": p.get("attrs") or {},
        }

    # ---- пакетный поиск -------------------------------------------------------------------------
    def search_batch(self, queries: Sequence[Any], limit: int = DEFAULT_LIMIT) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        # Разворачиваем строки, очищаем, сохраняем количество.
        for raw in queries[:MAX_BATCH]:
            if isinstance(raw, dict):
                cleaned = clean_query_line(raw.get("text") or raw.get("query"), raw.get("qty"))
            else:
                cleaned = clean_query_line(raw)
            items.append(cleaned)

        # Индекс после загрузки доступен только на чтение, текст запроса движок хранит
        # в threading.local — поэтому пакет считаем в пуле потоков (100 строк < 5 с),
        # сохраняя порядок строк. Перезагрузка каталога идёт под self._lock отдельно.
        def _one(item: Dict[str, Any]) -> Dict[str, Any]:
            text = item["text"]
            if not text:
                return {"query": "", "status": "empty", "qty": item["qty"], "results": []}
            res = self._engine.process_query(text)
            shaped = self._shape_single(text, res, limit)
            shaped["qty"] = item["qty"]
            return shaped

        if len(items) <= 1:
            return [_one(it) for it in items]
        from concurrent.futures import ThreadPoolExecutor
        workers = min(BATCH_WORKERS, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_one, items))

    # ---- перезагрузка каталога ------------------------------------------------------------------
    def reload(self, download: bool = True) -> Dict[str, Any]:
        """Пересобирает каталог сайта. download=True — скачать свежие выгрузки, иначе пересобрать локально."""
        with self._lock:
            try:
                if download:
                    from src.site_catalog import refresh
                    rep = refresh()
                else:
                    import glob

                    from src.site_catalog import UPLOAD_DIR, build_site_catalog
                    files = sorted(glob.glob(os.path.join(UPLOAD_DIR, "*.xlsx")))
                    if not files:
                        return {"ok": False, "message": f"Нет файлов в {UPLOAD_DIR} для пересборки"}
                    rep = build_site_catalog(files, {})
            except Exception as exc:  # сеть/битая выгрузка — не роняем сервис
                return {"ok": False, "message": f"Не удалось обновить каталог: {exc}"}
            # Сброс кэша индекса: движок перечитает CSV по новому mtime при следующем запросе.
            self._engine._site_engine = None
            self._engine._site_mtime = 0.0
            stats = self._engine.get_catalog_stats()
            return {
                "ok": True,
                "message": f"Каталог обновлён: {stats.get('total', 0)} поз. (в наличии {stats.get('in_stock', 0)})",
                "total": rep.get("total"),
                "stats": stats,
            }

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return self._engine.get_catalog_stats()


# --------------------------------------------------------------------------------------------------
# Выгрузка результатов пакетного подбора в .xlsx (openpyxl)
# --------------------------------------------------------------------------------------------------
_BATCH_HEADERS = [
    "Исходный запрос", "Количество", "Распознанный запрос", "Статус",
    "Артикул (топ-1)", "Название (топ-1)", "Бренд", "Тип совпадения",
    "Наличие", "Цена", "Ссылка",
    "Альтернатива 2", "Альтернатива 3",
]


def build_batch_xlsx(rows: List[Dict[str, Any]], source_headers: Optional[Sequence[str]] = None,
                     source_rows: Optional[Sequence[Sequence[Any]]] = None) -> bytes:
    """Собирает красивый .xlsx: исходные столбцы пользователя + столбцы результатов справа.

    Если переданы source_headers/source_rows — они идут первыми (как в исходном файле),
    справа добавляются результаты. Иначе — компактный набор столбцов результатов.
    Возвращает байты готового файла.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Подбор аналогов"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2F5496")
    link_font = Font(color="0563C1", underline="single")

    if source_headers:
        headers = list(source_headers) + _BATCH_HEADERS
    else:
        headers = _BATCH_HEADERS[:3] + ["Статус"] + _BATCH_HEADERS[4:]

    ws.append(headers)
    for col, _ in enumerate(headers, 1):
        c = ws.cell(row=1, column=col)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    n_source = len(source_headers) if source_headers else 0
    for i, r in enumerate(rows):
        results = r.get("results") or []
        top1 = results[0] if results else {}
        alt2 = results[1] if len(results) > 1 else {}
        alt3 = results[2] if len(results) > 2 else {}
        row_vals: List[Any] = []
        if source_headers and source_rows is not None and i < len(source_rows):
            src = source_rows[i]
            row_vals.extend([src[c] if c < len(src) else "" for c in range(n_source)])
        else:
            row_vals.extend([r.get("query", ""), r.get("qty")])
        row_vals.extend([
            r.get("corrected", ""),
            r.get("status", ""),
            top1.get("sku", ""),
            top1.get("name", ""),
            top1.get("brand", ""),
            top1.get("match_type", ""),
            top1.get("stock", ""),
            top1.get("price_display", ""),
            top1.get("url", ""),
            _alt_label(alt2),
            _alt_label(alt3),
        ])
        ws.append(row_vals)
        # Кликабельные ссылки на товар.
        row_idx = i + 2
        url_col = headers.index("Ссылка") + 1
        url_val = row_vals[url_col - 1]
        if url_val:
            cell = ws.cell(row=row_idx, column=url_col)
            cell.hyperlink = url_val
            cell.font = link_font

    # Автоподбор ширины столбцов.
    for col, title in enumerate(headers, 1):
        max_len = len(str(title))
        for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(max_len + 2, 10), 60)
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _alt_label(p: Dict[str, Any]) -> str:
    if not p:
        return ""
    sku = p.get("sku", "")
    price = p.get("price_display", "")
    return f"{sku} · {price}".strip(" ·")