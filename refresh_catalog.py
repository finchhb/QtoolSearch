"""
refresh_catalog.py - скачивание выгрузок qtool.ru (/upload) и пересборка каталога сайта.

Примеры:
  python refresh_catalog.py                  # скачать свежие xlsx, обновить ссылки и каталог
  python refresh_catalog.py --rebuild        # без сети: пересобрать из data/uploads/*.xlsx
  python refresh_catalog.py --file a.xlsx --file b.xlsx   # без сети: собрать из своих файлов
"""
import argparse
import glob
import json
import os
import sys

from src.site_catalog import MANIFEST, SITE_CSV, UPLOAD_DIR, build_site_catalog, fetch_site_urls, refresh


def _print_report(rep: dict) -> None:
    total = rep.get("total", 0)
    prev = rep.get("prev_total", 0)
    diff = f" (было {prev})" if prev else ""
    print(f"Каталог: {SITE_CSV}")
    print(f"Позиций: {total}{diff}")
    by_family = rep.get("by_family") or {}
    if by_family:
        print("По группам: " + ", ".join(f"{k} {v}" for k, v in sorted(by_family.items(), key=lambda x: -x[1])))
    for warn in rep.get("warnings") or []:
        print(f"Внимание: {warn}")
    for src in rep.get("sources") or rep.get("downloads") or []:
        name = src.get("file") or src.get("url") or ""
        status = src.get("status")
        prefix = f"  {status:12}" if status else "  "
        print(f"{prefix}{name}")
    print(f"Манифест: {MANIFEST}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Обновление каталога qtool.ru для детерминированного поиска")
    parser.add_argument("--dir", default=UPLOAD_DIR, help="куда скачивать xlsx (по умолчанию data/uploads)")
    parser.add_argument("--rebuild", action="store_true", help="не скачивать: пересобрать из --dir/*.xlsx")
    parser.add_argument("--file", action="append", default=[], help="локальный xlsx (можно несколько), без сети")
    parser.add_argument("--urls", action="store_true", help="при --rebuild обновить ссылки из sitemap (нужна сеть)")
    parser.add_argument("--json", action="store_true", help="вывести отчёт в JSON")
    args = parser.parse_args(argv)

    try:
        if args.file:
            rep = build_site_catalog(args.file, {})
        elif args.rebuild:
            files = sorted(glob.glob(os.path.join(args.dir, "*.xlsx")))
            if not files:
                print(f"В {args.dir} нет xlsx-файлов", file=sys.stderr)
                return 1
            rep = build_site_catalog(files, fetch_site_urls() if args.urls else {})
        else:
            rep = refresh(args.dir)
    except Exception as exc:  # сеть, битая выгрузка, отклонение объёма
        print(f"Не удалось обновить каталог: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        _print_report(rep)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
