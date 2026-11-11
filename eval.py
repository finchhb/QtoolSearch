"""
eval.py - прогон качества подбора. Запуск:  python eval.py [путь_к_xlsx_с_эталонами] [--llm | --training]

1) data/test_dataset.json (105 запросов): точность выбора действия (подбор / уточнение / аналоги) и определения группы ISO
   по категориям. Это проверка парсера, не качества выдачи.
2) Необязательный xlsx с эталонами (по умолчанию data/queries.xlsx, если файл есть). Нужны колонки: запрос
   (заголовок содержит «запрос» или «query») и эталонный артикул (заголовок содержит «эталон», «артикул», «sku» или «expected»;
   несколько артикулов — через ; , или перенос строки). Считает hit@1 и hit@5 — попал ли эталон в первую позицию / в топ-5.
3) Ключ --llm: прогнать с включённой проверкой LLM (AUDIT_SAMPLE_RATE=1) и показать, как часто LLM правит парсер.
--training: прогон таблицы обучения (data/training_examples.csv) без применения самих примеров — показывает, где парсер ещё ошибается.
Подробный разбор уходит в data/eval_report.csv.
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict

if "--training" in sys.argv:
    os.environ["TRAINING_DISABLE"] = "1"  # проверяем парсер БЕЗ подсказок из таблицы примеров
if "--llm" in sys.argv:
    os.environ["AUDIT_SAMPLE_RATE"] = "1"
    os.environ["REVIEW_MAX_PER_DAY"] = os.environ.get("REVIEW_MAX_PER_DAY", "1000")
else:
    os.environ["REVIEW_ENABLED"] = "0"
os.environ.setdefault("SKIP_NETWORK_SYNC", "1")

from src.engine import ToolAdvisorEngine  # noqa: E402
from src.materials_mapping import detect_iso_group  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9А-Я]", "", str(s).upper())


def read_gold(path):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = [[("" if c is None else str(c)) for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
    except ImportError:
        from build_catalog import _read_xlsx_rows_pure_python
        rows = _read_xlsx_rows_pure_python(path, skiprows=0, max_cols=20)
    if not rows:
        return []
    head = [h.lower() for h in rows[0]]
    qi = next((i for i, h in enumerate(head) if "запрос" in h or "query" in h), None)
    gi = next((i for i, h in enumerate(head) if any(k in h for k in ("эталон", "артикул", "sku", "expected"))), None)
    if qi is None or gi is None:
        print(f"[!] В {path} не нашёл колонки «запрос» и «эталон/артикул» (заголовки: {rows[0][:8]})")
        return []
    out = []
    for r in rows[1:]:
        if len(r) > max(qi, gi) and r[qi].strip():
            gold = [norm(x) for x in re.split(r"[;,\n]", r[gi]) if norm(x)]
            out.append((r[qi].strip(), gold))
    return out


def eval_training(e):
    """Золотой набор: все примеры технолога из data/training_examples.csv, прогнанные через парсер без этих примеров."""
    from src import training
    rows = [r for r in training.list_examples(100000) if (r.get("status") or "active") != "off"]
    if not rows:
        print("Таблица примеров пуста: добавь примеры через форму «Обучить парсер» (чат или админка).")
        return
    norm_op = lambda x: {"medium": "semi_finishing"}.get(x or "", x or "")  # noqa: E731
    n = iso_n = iso_ok = op_n = op_ok = sku_n = h1 = h5 = 0
    out = []
    for r in rows:
        q = r["query"]
        a = e._detect_search_args(q)
        res = e.process_query(q, force_local=True)
        skus = [norm(p.get("sku", "")) for p in (res.get("tool_result") or {}).get("products", [])[:5]]
        row = {"id": r["id"], "query": q, "correct_iso": r["correct_iso"], "parser_iso": a["iso_group"] or "",
               "correct_op": r["correct_operation"], "parser_op": norm_op(a["operation"]), "correct_skus": r["correct_skus"], "top_skus": ";".join(skus), "comment": r["comment"]}
        n += 1
        if r["correct_iso"]:
            iso_n += 1
            row["iso_ok"] = row["parser_iso"] == r["correct_iso"]
            iso_ok += row["iso_ok"]
        if r["correct_operation"]:
            op_n += 1
            row["op_ok"] = row["parser_op"] == norm_op(r["correct_operation"])
            op_ok += row["op_ok"]
        want = [norm(x) for x in re.split(r"[;,\n]", r["correct_skus"]) if norm(x)]
        if want:
            sku_n += 1
            hit = lambda sk: any(sk == w or sk.startswith(w) or w.startswith(sk) for w in want if sk)  # noqa: E731
            row["hit1"], row["hit5"] = bool(skus) and hit(skus[0]), any(hit(sk) for sk in skus)
            h1 += row["hit1"]
            h5 += row["hit5"]
        out.append(row)
    pct = lambda a_, b_: f"{a_}/{b_} ({100 * a_ // max(b_, 1)}%)"  # noqa: E731
    print(f"\n=== Таблица обучения: {n} примеров (парсер БЕЗ подсказок из таблицы) ===")
    print(f"группа ISO: {pct(iso_ok, iso_n)} | вид обработки: {pct(op_ok, op_n)} | артикул эталона в топ-1: {pct(h1, sku_n)}, в топ-5: {pct(h5, sku_n)}")
    bad = [o for o in out if o.get("iso_ok") is False or o.get("op_ok") is False or o.get("hit5") is False]
    for o in bad[:30]:
        print(f"  №{o['id']} {o['query'][:70]} | ISO ждали {o['correct_iso'] or '—'} получили {o['parser_iso'] or '—'} | обработка ждали {o['correct_op'] or '—'} получили {o['parser_op'] or '—'}")
    keys = sorted({k for o in out for k in o})
    with open("data/eval_training_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys, delimiter=";")
        w.writeheader()
        w.writerows(out)
    print("Отчёт: data/eval_training_report.csv")


def main():
    e = ToolAdvisorEngine(auto_sync_rinscom=False)
    if "--training" in sys.argv:
        eval_training(e)
        return
    report = []

    # ---- 1. test_dataset.json
    data = json.load(open("data/test_dataset.json", encoding="utf-8"))
    by_cat = defaultdict(lambda: {"n": 0, "act": 0, "iso_n": 0, "iso": 0})
    misses = []
    for it in data:
        q, cat = it["query"], it.get("category", "")
        res = e.process_query(q)
        act_ok = res["decision"] == it.get("expected_action")
        c = by_cat[cat]
        c["n"] += 1
        c["act"] += act_ok
        iso_ok = ""
        if cat == "material_gost" and it.get("expected_iso"):
            c["iso_n"] += 1
            got = detect_iso_group(q)
            iso_ok = got == it["expected_iso"]
            c["iso"] += iso_ok
            if not iso_ok:
                misses.append((q, it["expected_iso"], got or "—"))
        report.append({"set": "dataset", "category": cat, "query": q, "expected_action": it.get("expected_action"), "decision": res["decision"],
                       "action_ok": act_ok, "iso_ok": iso_ok, "llm_checked": res.get("llm_checked", False)})
    print("\n=== test_dataset.json (проверка парсера) ===")
    print(f"{'категория':26}{'запросов':>9}{'действие верно':>16}{'ISO по материалу':>20}")
    tn = ta = 0
    for cat, c in by_cat.items():
        iso_txt = f"{c['iso']}/{c['iso_n']}" if c["iso_n"] else "—"
        print(f"{cat:26}{c['n']:>9}{c['act']:>12}/{c['n']:<3}{iso_txt:>20}")
        tn += c["n"]
        ta += c["act"]
    print(f"{'ИТОГО':26}{tn:>9}{ta:>12}/{tn}")
    if misses:
        print("\nОшибки определения материала:")
        for q, exp, got in misses:
            print(f"  ожидали {exp}, получили {got}: {q}")

    # ---- 2. эталоны по артикулам
    gold_path = next((a for a in sys.argv[1:] if a.lower().endswith(".xlsx")), "data/queries.xlsx")
    if os.path.exists(gold_path):
        gold = read_gold(gold_path)
        h1 = h5 = 0
        for q, g in gold:
            res = e.process_query(q)
            skus = [norm(p.get("sku", "")) for p in (res.get("tool_result") or {}).get("products", [])[:5]]
            hit = lambda s: any(s == x or s.startswith(x) or x.startswith(s) for x in g if s)
            k1 = bool(skus) and hit(skus[0])
            k5 = any(hit(s) for s in skus)
            h1 += k1
            h5 += k5
            report.append({"set": "gold", "category": "", "query": q, "expected_action": ";".join(g), "decision": res["decision"],
                           "action_ok": "", "iso_ok": "", "llm_checked": res.get("llm_checked", False), "hit1": k1, "hit5": k5, "top1": skus[0] if skus else ""})
        if gold:
            print(f"\n=== эталоны ({gold_path}) ===\nзапросов: {len(gold)} | hit@1: {h1} ({100*h1//len(gold)}%) | hit@5: {h5} ({100*h5//len(gold)}%)")
    else:
        print(f"\n(Файл эталонов {gold_path} не найден — положи его в data/ или укажи путь аргументом.)")

    if "--llm" in sys.argv:
        print("\n=== проверка LLM ===\n", e.reviewer.stats, "\nПодробности: data/review_log.jsonl")

    keys = sorted({k for r in report for k in r})
    with open("data/eval_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(report)
    print("\nОтчёт: data/eval_report.csv")


if __name__ == "__main__":
    main()
