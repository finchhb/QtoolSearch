"""
import_docs.py - загрузка справочников компании в движок подбора.  Запуск:
    python import_docs.py  <папка или файлы .xlsx>  [--dry]
Ищет по названиям листов (имена файлов могут быть любыми):
  • лист «Марки сплавов по ISO»        -> data/materials_iso.csv  (марка заготовки по ГОСТ -> группа ISO)
  • лист «аналоги сплавов Дескар»       -> data/grades_docs.csv    (сплавы Deskar / INTOOL / ZCC-CT -> группы ISO по классам P05…K35)
  • файл Келит: лист «Лист 1» с колонкой «Обозначение сплава» -> data/grades_docs.csv (сплавы Kelite -> ISO из описания)
После импорта пересобери каталог (админка -> «Скачать прайс» или python build_catalog.py ...): ISO сплавов из справочников
уточняет ISO, который раньше брался из grades.csv и атрибута сайта (правила — в build_catalog.apply_docs_iso). Отчёт об аномалиях печатается в консоль и пишется в data/import_docs_report.txt.
Данные в таблице «Марки» разбираются по колонке «Обозначение по ISO» (она заполнена только в первой строке блока);
явные опечатки исправляются и попадают в отчёт (например, блок «Чугуны» помечен P — по ISO это K).
"""
import csv
import glob
import os
import re
import sys
from collections import defaultdict

import openpyxl

OUT_MATERIALS = os.path.join("data", "materials_iso.csv")
OUT_GRADES = os.path.join("data", "grades_docs.csv")
OUT_REPORT = os.path.join("data", "import_docs_report.txt")
LATIN2CYR = str.maketrans("abcehkmoptxy", "авсенкмортху")  # похожие латинские буквы -> кириллица (для сравнения марок)
report = []


def say(msg):
    print(msg)
    report.append(msg)


def collect_files(args):
    files = []
    for a in args:
        if os.path.isdir(a):
            files += glob.glob(os.path.join(a, "*.xlsx"))
        elif a.lower().endswith(".xlsx"):
            files.append(a)
    return files


def split_marks(cell):
    """Ячейка с марками -> список очищенных обозначений (алиасы в скобках — отдельными марками)."""
    out = []
    for part in re.split(r"[,;\n]+", str(cell or "")):
        part = part.strip()
        if not part:
            continue
        alias = re.findall(r"\(([^()]*)\)", part)
        main = re.sub(r"\([^()]*\)", "", part).strip()
        cands = [main] + [a.strip() for a in alias if re.search(r"\d", a) and " " not in a.strip() and "%" not in a]
        for c in cands:
            c = c.strip(" .")
            if not c or ":" in c or len(c) > 30:
                continue
            out.append(c)
    return out


def mark_regex(mark):
    """Регулярное выражение марки: регистр не важен, между буквами и цифрами допустим пробел/дефис, границы слова обязательны."""
    m = mark.lower().replace("ё", "е").replace(" ", "")
    if re.fullmatch(r"\d+", m) or len(m) < 3:  # голые числа («45», «20») и совсем короткие — слишком неоднозначны
        return None
    esc = re.escape(m)
    esc = re.sub(r"(?<=[а-яa-z])(?=\d)", r"[\\s-]?", esc)  # сч20 / сч 20 / сч-20
    esc = esc.replace("ст[\\s-]?", "ст\\.?[\\s]?") if m.startswith("ст") and re.match(r"ст\d", m) else esc
    return r"(?<![а-яa-z0-9])" + esc + r"(?![а-яa-z0-9])"


def import_marks(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Марки сплавов по ISO"]
    rows = [r for r in ws.iter_rows(values_only=True)]
    iso = None
    marks, seen = [], {}
    for r in rows[5:]:
        a, b, c = (r + (None, None, None))[:3]
        if a and str(a).strip().upper() in ("P", "M", "K", "N", "S", "H"):
            iso = str(a).strip().upper()
            if str(b or "").strip().lower().startswith("чугун") and iso != "K":
                say(f"  ИСПРАВЛЕНО: блок «Чугуны» в таблице помечен {iso}, по ISO это K — поставил K")
                iso = "K"
        if not c or iso is None:
            continue
        for mk in split_marks(c):
            rx = mark_regex(mk)
            if not rx:
                continue
            key = mk.lower().replace(" ", "")
            if key in seen and seen[key] != iso:
                say(f"  КОНФЛИКТ: марка «{mk}» есть и в {seen[key]}, и в {iso} — оставил {seen[key]}")
                continue
            if key in seen:
                continue
            seen[key] = iso
            marks.append((rx, iso, mk))
    return marks


def import_deskar_analogs(path):
    ws = openpyxl.load_workbook(path, data_only=True)["аналоги сплавов Дескар"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = rows[2]
    cols = {i: str(h) for i, h in enumerate(hdr) if str(h) in ("Deskar", "INTOOL", "ZCC-CT")}
    docs = defaultdict(lambda: {"letters": [], "classes": set(), "brand": ""})
    for r in rows[3:24]:
        cls = str(r[2] or "")
        if not re.fullmatch(r"[PMKNSH]\d+", cls):
            continue
        for ci, brand in cols.items():
            for g in re.split(r"[\s,;]+", str(r[ci] or "").strip()):
                g = g.upper()
                if not g:
                    continue
                d = docs[g]
                if cls[0] not in d["letters"]:
                    d["letters"].append(cls[0])
                d["classes"].add(cls)
                d["brand"] = brand
    return docs


def import_kelite(path):
    ws = openpyxl.load_workbook(path, data_only=True)["Лист 1"]
    docs = {}
    for r in list(ws.iter_rows(values_only=True))[1:]:
        g, desc = (r[0] or "").strip().upper(), str(r[1] or "")
        m = re.search(r"ISO\s+([PMKNSH](?:[\d–\-,\sPMKNSH]*?))(?=[.;:]|\s[А-Яа-яA-Za-z]{2,}|$)", desc)
        if not g or not m:
            continue
        letters = []
        for ch in re.findall(r"[PMKNSH]", m.group(1)):
            if ch not in letters:
                letters.append(ch)
        if letters:
            docs[g] = {"letters": letters, "classes": set(), "brand": "Kelite"}
    return docs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return
    files = collect_files(args)
    marks, grades = [], {}
    for f in files:
        try:
            names = openpyxl.load_workbook(f, read_only=True).sheetnames
        except Exception as e:
            say(f"[пропуск] {f}: {e}")
            continue
        base = os.path.basename(f)
        if "Марки сплавов по ISO" in names and not marks:
            marks = import_marks(f)
            say(f"Марки заготовок: {len(marks)} из «{base}»")
        if "аналоги сплавов Дескар" in names:
            d = import_deskar_analogs(f)
            grades.update({k: v for k, v in d.items()})
            say(f"Сплавы Deskar/INTOOL/ZCC-CT из таблицы аналогов: {len(d)} из «{base}»")
        if "Лист 1" in names and "Стружколомы" in names and "аналоги сплавов Дескар" not in names:
            d = import_kelite(f)
            grades.update(d)
            say(f"Сплавы Kelite с указанием ISO: {len(d)} из «{base}»")
    if "--dry" in sys.argv:
        return
    os.makedirs("data", exist_ok=True)
    if marks:
        with open(OUT_MATERIALS, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["pattern", "iso", "note"])
            for rx, iso, mk in marks:
                w.writerow([rx, iso, f"методичка: {mk}"])
    if grades:
        with open(OUT_GRADES, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["grade", "brand", "iso_groups", "classes", "scope", "source"])
            for g, d in sorted(grades.items()):
                # scope: all — справочник описывает все группы сплава (Келит); pmk — таблица аналогов покрывает только P/M/K, группы S/N/H не трогаем;
                # add_only — для Deskar богаче лист «Сплавы» (уже в grades.csv): справочник используется, только если сплава там нет
                scope = "all" if d["brand"] == "Kelite" else ("add_only" if d["brand"] == "Deskar" else "pmk")
                w.writerow([g, d["brand"], ",".join(d["letters"]), " ".join(sorted(d["classes"])), scope, "справочник компании"])
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    say(f"Записано: {OUT_MATERIALS if marks else '—'}, {OUT_GRADES if grades else '—'}. Пересобери каталог, чтобы ISO сплавов обновился.")


if __name__ == "__main__":
    main()
