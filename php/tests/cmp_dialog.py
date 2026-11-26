# -*- coding: utf-8 -*-
"""Сравнение PHP Dialog::isClarification с Python is_clarification."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from src.catalog_search import is_clarification  # noqa: E402
from src.site_catalog import load_site_catalog  # noqa: E402

PHP = os.path.join(os.path.dirname(REPO), "tools", "php", "php.exe")
PROBE = os.path.join(HERE, "_dialog_probe.php")

QUERIES = [
    "12", "под CNMG12", "чистовая", "под хвостовик 20", "MTA2 велдон 10",
    "SK40", "HSK63", "ER32", "cnmg12", "DCGT 11", "CNMG 120408",
    "PCLNR 2525M12", "MCBNR2020", "метчик M10", "державка 2020 под CNMG12",
    "mcbnr 2020", "cnmg", "dcmt", "", "под пластину DNMG15", "8,5", "купить",
    "под APMT1604", "черновая", "наружная", "правая", "под 20 хвостовик",
    "M10", "м10", "16", "под пластину", "для нержавейки", "расточная",
    "_holder", "сверло 8", "фреза 10", "WNMG080408", "apmt", "120408",
]


def build_prefixes():
    items = load_site_catalog()
    prefixes = {}
    for it in items:
        attrs = it.get("attrs") or {}
        iso = str(attrs.get("iso_code") or "").strip().upper()
        if len(iso) >= 4:
            prefixes[iso[:4]] = prefixes.get(iso[:4], 0) + 1
    return prefixes


def main():
    prefixes = build_prefixes()
    data = {"queries": QUERIES, "insert_prefixes": list(prefixes.keys())}
    res = subprocess.run([PHP, PROBE], input=json.dumps(data),
                         capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        print("PHP ERROR:", res.stderr)
        sys.exit(1)
    php_out = json.loads(res.stdout)
    pset = set(prefixes.keys())
    bad = 0
    for q, php in zip(QUERIES, php_out):
        py = is_clarification(q, pset)
        if py != php:
            bad += 1
            print(f"MISMATCH {q!r}: py={py} php={php}")
    print(f"{len(QUERIES)} queries, {bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()