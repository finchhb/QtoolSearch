"""
eval_site.py - офлайн-проверка качества детерминированного поиска по каталогу сайта.

Читает эталонный набор data/site_eval.json (запрос + ожидаемая группа/атрибуты/подстрока в топе)
и печатает hit@1/hit@5 по подстроке, совпадение группы и параметров.

  python eval_site.py
  python eval_site.py --golden data/site_eval.json --limit 5 --verbose
"""
import argparse
import json
import os
import sys

from src.catalog_search import CatalogSearchEngine
from src.site_catalog import SITE_CSV, load_site_catalog

DEFAULT_GOLDEN = os.path.join("data", "site_eval.json")


def _num_eq(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-6
    except (TypeError, ValueError):
        return str(a) == str(b)


def _check(res, exp) -> list:
    errors = []
    if "family" in exp and res.get("family") != exp["family"]:
        errors.append(f"группа: ждали {exp['family']}, получили {res.get('family')}")
    if "level" in exp and res.get("level") != exp["level"]:
        errors.append(f"уровень: ждали {exp['level']}, получили {res.get('level')}")
    if "total_min" in exp and int(res.get("total_found") or 0) < int(exp["total_min"]):
        errors.append(f"найдено {res.get('total_found')} < {exp['total_min']}")
    if "total_max" in exp and int(res.get("total_found") or 0) > int(exp["total_max"]):
        errors.append(f"найдено {res.get('total_found')} > {exp['total_max']}")
    for key in ("insert_code", "holder_code", "compatible_insert", "fits_holder"):
        if key in exp and res.get(key) != exp[key]:
            errors.append(f"{key}: ждали {exp[key]}, получили {res.get(key)}")
    for key, want in (exp.get("attrs") or {}).items():
        got = (res.get("parsed") or {}).get(key)
        if not _num_eq(got, want):
            errors.append(f"{key}: ждали {want}, получили {got}")
    for want in exp.get("chips_include") or []:
        if not any(want.casefold() in str(c).casefold() for c in res.get("chips") or []):
            errors.append(f"нет подсказки «{want}»")
    td = exp.get("tap_drill")
    if td:
        got = res.get("tap_drill") or {}
        for key, want in td.items():
            if not _num_eq(got.get(key), want):
                errors.append(f"tap_drill.{key}: ждали {want}, получили {got.get(key)}")
    want_sub = exp.get("must_include")
    if want_sub:
        top = (res.get("products") or [])[: int(exp.get("top", 5))]
        blob = " ".join(f"{p.get('sku', '')} {p.get('name', '')}" for p in top).casefold()
        if want_sub.casefold() not in blob:
            errors.append(f"в топе нет «{want_sub}»")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Проверка поиска по эталонным запросам")
    parser.add_argument("--golden", default=DEFAULT_GOLDEN)
    parser.add_argument("--catalog", default=SITE_CSV)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    with open(args.golden, "r", encoding="utf-8-sig") as f:
        cases = json.load(f)
    items = load_site_catalog(args.catalog)
    if not items:
        print(f"Нет каталога: {args.catalog}. Сначала запустите python refresh_catalog.py", file=sys.stderr)
        return 2
    engine = CatalogSearchEngine(items)

    passed = 0
    for case in cases:
        query = case["query"]
        res = engine.search(query, limit=args.limit, in_stock_only=case.get("in_stock_only", True))
        errors = _check(res, case)
        if errors:
            print(f"FAIL  {query}")
            for err in errors:
                print(f"      - {err}")
        else:
            passed += 1
            if args.verbose:
                top = res.get("products") or []
                first = f"{top[0].get('sku', '')} | {top[0].get('name', '')[:60]}" if top else "—"
                print(f"ok    {query}  [{res.get('level')}, {res.get('total_found')}]  {first}")

    total = len(cases)
    print(f"\nИтог: {passed}/{total} запросов прошли (каталог: {len(items)} позиций)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
