# -*- coding: utf-8 -*-
"""Сравнение PHP CatalogSearch.search() с Python CatalogSearchEngine.search().

Каталог берётся из Python load_site_catalog() и передаётся в PHP тем же списком
(_items.json), чтобы сравнивать именно логику движка, а не приём данных.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from src.catalog_search import CatalogSearchEngine  # noqa: E402
from src.site_catalog import load_site_catalog  # noqa: E402
from cmp_query import QUERIES  # noqa: E402

PHP = os.path.join(os.path.dirname(REPO), "tools", "php", "php.exe")
PROBE = os.path.join(HERE, "_search_probe.php")
ITEMS = os.path.join(HERE, "_items.json")


def eq(a, b, path=""):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if path.endswith(".score"):
            return abs(float(a) - float(b)) <= 0.011
        return float(a) == float(b)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return False
        return all(eq(a[k], b[k], f"{path}.{k}") for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq(x, y, f"{path}[{i}]") for i, (x, y) in enumerate(zip(a, b)))
    if isinstance(a, dict) and isinstance(b, list):
        return len(a) == 0 and len(b) == 0
    if isinstance(a, list) and isinstance(b, dict):
        return len(a) == 0 and len(b) == 0
    return a == b


def diff_fields(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += diff_fields(a.get(k), b.get(k), f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_fields(x, y, f"{path}[{i}]")
        return out
    if not eq(a, b, path):
        out.append(f"{path}: py={a!r} php={b!r}")
    return out


def main():
    items = load_site_catalog()
    with open(ITEMS, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    engine = CatalogSearchEngine(items)
    res = subprocess.run([PHP, PROBE], input=json.dumps(QUERIES),
                         capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        print("PHP ERROR:", res.stderr)
        sys.exit(1)
    php_out = json.loads(res.stdout)
    bad = 0
    for q, php in zip(QUERIES, php_out):
        py = engine.search(q)
        if not eq(py, php):
            bad += 1
            print(f"\n=== MISMATCH: {q!r}")
            for line in diff_fields(py, php)[:25]:
                print("  ", line)
    print(f"\n{len(QUERIES)} queries, {bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()