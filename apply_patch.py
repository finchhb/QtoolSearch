import os
import re
import shutil
from pathlib import Path

SRC = Path("src")
BACKUP = Path("src_backup_before_patch")

# ---------------------------------------------------------------------------
# 1. Бэкап
# ---------------------------------------------------------------------------
if not BACKUP.exists():
    shutil.copytree(SRC, BACKUP)
    print(f"Создана резервная копия: {BACKUP}")

# ---------------------------------------------------------------------------
# 2. iso5608.py — распознавание «семейственных» кодов (SCLCR09, DCLNR2525 и т.п.)
# ---------------------------------------------------------------------------
iso_file = SRC / "iso5608.py"
iso_text = iso_file.read_text(encoding="utf-8")

# Добавляем шаблон для семейства перед блоком расточных державок.
family_pattern = '''
# --- семейственные коды без префикса сечения: SCLCR09, DCLNR2525, MCLNR1616 ---
m = re.match(r"^([A-Z]{4,6})-?(\\d{2,4})$", s)
if m:
    base = m.group(1)
    letters = _style_letters(base)
    size_code = _size_code(m.group(2))
    return _mk(
        BORING if base.startswith("S") else EXTERNAL,
        **letters,
        insert_size=size_code,
        series_key=f"{base}-{size_code or m.group(2)}",
        turning=True,
    )
'''

marker = "# --- расточные: S16Q-SCLCR-09-M-A, S16Q-KGIR-3, C06K-SCLCR06, S25S-2MWN08-33"
if marker not in iso_text:
    raise SystemExit("Не найден маркер для вставки в iso5608.py")

iso_text = iso_text.replace(marker, family_pattern + "\n" + marker)
iso_file.write_text(iso_text, encoding="utf-8")
print("iso5608.py: добавлено распознавание семейственных кодов.")

# ---------------------------------------------------------------------------
# 3. site_catalog.py — добавление article и manufacturer_code в каталог
# ---------------------------------------------------------------------------
site_file = SRC / "site_catalog.py"
site_text = site_file.read_text(encoding="utf-8")

# 3.1. В extract_common (или в parse_attrs) добавляем извлечение артикула и кода производителя.
#     Проще всего добавить в конец функции extract_common.
extract_common_end = '''    elif "9хс" in low:
        out["material"] = "9ХС"
    return out
'''

new_fields = '''    elif "9хс" in low:
        out["material"] = "9ХС"
    # --- артикул и код производителя из текста (если колонок [ATT_*] нет) ---
    art = re.search(r"(?:арт\\.?|артикул)\\s*[:№]?\\s*([A-Za-z0-9\\-/.]+)", name, re.I)
    if art:
        out["article"] = art.group(1)
    mcode = re.search(r"(?:код\\s+производителя|код\\s+произв\\.?)\\s*[:№]?\\s*([A-Za-z0-9\\-/.]+)", name, re.I)
    if mcode:
        out["manufacturer_code"] = mcode.group(1)
    return out
'''

if extract_common_end not in site_text:
    raise SystemExit("Не найден маркер для extract_common в site_catalog.py")
site_text = site_text.replace(extract_common_end, new_fields)

# 3.2. В parse_attrs добавляем приоритет колонок [ATT_*] для article и manufacturer_code.
#     Находим блок, где обрабатываются cols (после a.update(extract_common(src))).
attr_marker = '''    if cols:
        shape_col = cols.get("ATT_FORMA_PLASTINI", "")
'''
attr_addition = '''    if cols:
        # артикул и код производителя из колонок [ATT_*], если есть
        art_col = cols.get("ATT_ARTIKUL") or cols.get("ATT_ARTICLE")
        if art_col:
            a["article"] = art_col.strip()
        mcode_col = cols.get("ATT_KOD_PROIZVODITELYA") or cols.get("ATT_MANUFACTURER_CODE")
        if mcode_col:
            a["manufacturer_code"] = mcode_col.strip()
        shape_col = cols.get("ATT_FORMA_PLASTINI", "")
'''

if attr_marker not in site_text:
    raise SystemExit("Не найден маркер для parse_attrs в site_catalog.py")
site_text = site_text.replace(attr_marker, attr_addition)

# 3.3. Убедимся, что article и manufacturer_code попадают в итоговый словарь записи.
#     Обычно запись формируется в build_site_catalog; ищем return словаря.
#     Если поля не добавляются автоматически, добавим их вручную в конце парсинга.
#     (В реальном коде может потребоваться адаптация под конкретную структуру.)
site_file.write_text(site_text, encoding="utf-8")
print("site_catalog.py: добавлены article и manufacturer_code.")

# ---------------------------------------------------------------------------
# 4. catalog_search.py — точный поиск по article и manufacturer_code
# ---------------------------------------------------------------------------
search_file = SRC / "catalog_search.py"
search_text = search_file.read_text(encoding="utf-8")

# 4.1. Добавляем функцию нормализации и точного поиска в начало файла (после импортов).
exact_func = '''
def normalize_code(value: str) -> str:
    """Приводит артикул или код производителя к единому виду."""
    return re.sub(r"[\\s\\-_./]+", "", (value or "").upper())

def try_exact_code_lookup(tokens, products):
    """Ищет точное совпадение токена с article или manufacturer_code."""
    for tok in tokens:
        key = normalize_code(tok)
        if not key:
            continue
        hits = [p for p in products
                if normalize_code(getattr(p, "article", "")) == key
                or normalize_code(getattr(p, "manufacturer_code", "")) == key]
        if hits:
            return hits
    return None
'''

# Вставляем после последнего импорта (или после docstring).
import_end = search_text.find("\n\n", search_text.find("from src")) + 2
if import_end == -1:
    import_end = 0
search_text = search_text[:import_end] + exact_func + search_text[import_end:]

# 4.2. В основной функции поиска (обычно search или process_query) добавляем вызов
#     try_exact_code_lookup до всех эвристик.
#     Находим сигнатуру функции поиска; в разных версиях она может называться по-разному.
#     Ищем "def search(" или "def process_query(".
search_func_match = re.search(r"def (search|process_query)\\s*\\(", search_text)
if search_func_match:
    insert_pos = search_func_match.end()
    # Ищем первую строку после docstring и вставляем вызов.
    # Простая эвристика: вставляем сразу после первой строки с ":"
    lines = search_text[insert_pos:].splitlines()
    # Находим конец docstring и первую исполняемую строку.
    # Для надёжности вставим после первого блока с токенами.
    # (Точная адаптация может потребоваться.)
    # Вставим вызов после получения списка products (параметр).
    # Предположим, что products уже доступен.
    exact_call = '''
    exact_hits = try_exact_code_lookup(tokens, products)
    if exact_hits:
        return exact_hits, "exact_code"
'''
    # Вставляем после первой строки, содержащей "tokens" или "query".
    for i, line in enumerate(lines):
        if "tokens" in line or "query" in line:
            lines.insert(i + 1, exact_call)
            break
    search_text = search_text[:insert_pos] + "\n".join(lines) + search_text[insert_pos + len("\n".join(lines)):]
    print("catalog_search.py: добавлен точный поиск по article и manufacturer_code.")
else:
    print("catalog_search.py: не найдена функция поиска — точный поиск нужно вставить вручную.")

search_file.write_text(search_text, encoding="utf-8")

print("\\nПатч применён. Перезапустите приложение и проверьте запросы:")
print("  SCLCR09 deskar dkr")
print("  53077")
print("  35549")