# -*- coding: utf-8 -*-
"""Сравнение PHP Query с Python Query на eval-запросах и краевых случаях."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from src.catalog_search import Query  # noqa: E402
from src.site_catalog import load_site_catalog  # noqa: E402

PHP = os.path.join(os.path.dirname(REPO), "tools", "php", "php.exe")
PROBE = os.path.join(HERE, "_query_probe.php")

EVAL = [
    "CNMG 120408", "снмг 1204O8", "CNMG120408", "СТМН 120408",
    "сверло 8,5 мм", "сверло под резьбу М10", "фреза концевая 10 мм 3 зуба",
    "метчик М10", "державка CKJNL2525M16", "цанга ER32 12", "зенкер 20 90",
    "развертка 10 H7", "пластина для нержавейки чистовая", "фреза BAP 400R 63-22-4T",
    "державка 2525 под CNMG1204", "державка под CNMG1204", "фреза 120 под APMT",
    "фреза под APMT1604", "державка 2525 под пластину CNMG1204",
    "фреза или корпус фрезы под пластину APMT1604",
    "расточная державка под пластину CCMT09T304", "под пластину CNMG1204",
    "фреза под пластину РПМТ1204", "пластина под державку MCLNR2525M12",
    "пластина для державки SCLCR2525M12", "пластина. Ромб. Размер 09.радиус 02",
    "державка 1616 под пластина Правая. Ромб. Размер 09",
    "державка хвост 16 под пластина Правая. Ромб. Размер 09",
    "патрон бт50 под велдон 25 длинной 100", "набор прижимов под 14 паз", "8,5", "купить",
]
EDGE = [
    "хвост 16", "SBHA12-20", "SBHA32", "SBHA", "кулачки к11-400",
    "втулка переходная морзе2 на морзе 1", "барпулер 2525", "калибр-пробка 5 H7",
    "6282-2002 инсайз", "сверлильный самозажимной патрон 1-16мм", "цанговый патрон",
    "DCGT 11", "DCGT09", "DCGT 11T302", "CNMG 1204 4325", "DCGT 11T302 FL K10",
    "CNMG120408PM4325", "сверло с квадратной пластиной", "пластина под державку",
    "державка расточная S20", "S16Q-SCLCR-09-M-A", "MCLNR2525M12", "mcbnr 2020",
    "фреза дисковая 100x2", "метчик машинный М8х1", "пластина треугольник размер 16",
    "ержавка 2525 под CNMG1204", "cnmg120408", "РПМТ1204", "апмт 1604",
    "пластина круглая 12", "державка наружная правая 2525", "ER32", "ER16",
    "патрон B16", "VDI30", "фреза шпоночная 8", "сверло 5D 10", "зенкер 90 град",
    "пластина WNMG080408 для стали", "державка 2020 под пластину ромб размер 09 правая",
]
QUERIES = EVAL + EDGE


def build_prefixes():
    items = load_site_catalog()
    prefixes = {}
    for it in items:
        attrs = it.get("attrs") or {}
        iso = str(attrs.get("iso_code") or "").strip().upper()
        if len(iso) >= 4:
            prefixes[iso[:4]] = prefixes.get(iso[:4], 0) + 1
    return prefixes


def py_dict(q):
    return {
        "text": q.text, "family": q.family, "category_hints": q.category_hints,
        "attrs": q.attrs, "insert_code": q.insert_code, "holder_code": q.holder_code,
        "thread": q.thread, "brand": q.brand, "free_tokens": q.free_tokens,
        "compat_insert": q.compat_insert, "compat_prefix": q.compat_prefix,
        "compat_shape": q.compat_shape, "compat_clearance": q.compat_clearance,
        "compat_hole": q.compat_hole, "compat_size": q.compat_size, "compat_hand": q.compat_hand,
        "compat_requested": q.compat_requested, "holder_compat": q.holder_compat,
        "holder_compat_code": q.holder_compat_code,
        "holder_compat_requested": q.holder_compat_requested, "shank_round": q.shank_round,
    }


def eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return False
        return all(eq(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
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
    if not eq(a, b):
        out.append(f"{path}: py={a!r} php={b!r}")
    return out


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
        py = py_dict(Query(q, pset))
        if not eq(py, php):
            bad += 1
            print(f"\n=== MISMATCH: {q!r}")
            for line in diff_fields(py, php):
                print("  ", line)
    print(f"\n{len(QUERIES)} queries, {bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()