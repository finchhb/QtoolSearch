# diagnose.py
import re
from pathlib import Path

for fname in ["site_catalog.py", "catalog_search.py"]:
    p = Path("src") / fname
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    print(f"\n{'='*70}\n{fname} — {len(lines)} строк\n{'='*70}")

    print("\n--- Все def (сигнатуры) ---")
    for i, ln in enumerate(lines):
        m = re.match(r"\s*def\s+(\w+)\s*\(", ln)
        if m:
            print(f"{i+1:5d}: {ln.strip()}")

    print("\n--- Все вхождения 'ATT_' (с контекстом ±4 строки) ---")
    shown = set()
    for i, ln in enumerate(lines):
        if "ATT_" in ln:
            start, end = max(0, i - 4), min(len(lines), i + 5)
            key = (start, end)
            if key in shown:
                continue
            shown.add(key)
            print(f"\n[строки {start+1}–{end}]")
            for j in range(start, end):
                mark = ">>>" if j == i else "   "
                print(f"{j+1:5d} {mark} {lines[j]}")

    print("\n--- Места, где формируется запись (return {...} или dict с 'name') ---")
    for i, ln in enumerate(lines):
        if re.search(r'return\s*\{|"name"\s*:|\["name"\]', ln):
            start, end = max(0, i - 3), min(len(lines), i + 15)
            print(f"\n[строки {start+1}–{end}]")
            for j in range(start, end):
                mark = ">>>" if j == i else "   "
                print(f"{j+1:5d} {mark} {lines[j]}")