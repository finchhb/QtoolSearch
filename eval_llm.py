"""
eval_llm.py - выбор LLM-провайдера по цифрам, а не по впечатлениям. Запуск:  python eval_llm.py [--limit N]
Нужны LLM_BASE_URL, LLM_API_KEY, LLM_MODELS (в .env или окружении, см. src/llm_client.py).

Для каждого запроса из data/llm_benchmark.json (75 фраз: разговорные, свежие и «длинный хвост» редких сплавов)
сравнивает с эталоном (группа ISO материала и вид обработки):
  - внутренний парсер сам;
  - LLM сама (её ответ на тот же вопрос, что получает проверяющий контур);
  - итоговая схема продукта: парсер, а там, где он не нашёл параметр, подставляется ответ LLM.
Печатает также долю невалидных ответов (не JSON), ошибок API, среднюю и p95-задержку и расход токенов.
ВНИМАНИЕ: эталоны в файле — черновик; технолог должен поправить спорные строки (поле "iso"/"op").
Отчёт по строкам: data/eval_llm_report.csv
"""
import csv
import json
import os
import statistics
import sys
import time

os.environ.setdefault("SKIP_NETWORK_SYNC", "1")
os.environ["REVIEW_ENABLED"] = "1"

from src.engine import ToolAdvisorEngine  # noqa: E402
from src.llm_client import LLMError  # noqa: E402
from src.materials_mapping import detect_explicit_operation, detect_iso_group  # noqa: E402

norm_op = lambda x: {"medium": "semi_finishing"}.get(x or "", x or "")  # noqa: E731


def main():
    e = ToolAdvisorEngine(auto_sync_rinscom=False)
    llm, rv = e.llm, e.reviewer
    if not llm.is_configured():
        print("LLM не настроена: задай LLM_BASE_URL, LLM_API_KEY и LLM_MODELS (в .env или окружении).")
        return
    items = json.load(open("data/llm_benchmark.json", encoding="utf-8"))
    if "--limit" in sys.argv:
        items = items[: int(sys.argv[sys.argv.index("--limit") + 1])]
    stat = {k: 0 for k in ("n", "p_iso", "l_iso", "c_iso", "p_op", "l_op", "c_op", "op_n", "bad_json", "api_err")}
    lat, tokens, rows = [], 0, []
    print(f"Модели: {llm.model} | {llm.base_url} | запросов: {len(items)}\n")
    for it in items:
        q, exp_iso, exp_op = it["q"], it["iso"], norm_op(it.get("op"))
        p_iso, p_op = detect_iso_group(q), norm_op(detect_explicit_operation(q))
        t0 = time.time()
        l_iso = l_op = ""
        err = ""
        try:
            v = rv.ask(q, {"text_query": q}, [])
            if v is None:
                stat["bad_json"] += 1
                err = "bad_json"
            else:
                l_iso, l_op = v["corrections"].get("iso_group", ""), norm_op(v["corrections"].get("operation", ""))
        except LLMError as ex:
            stat["api_err"] += 1
            err = str(ex)[:120]
        dt = time.time() - t0
        lat.append(dt)
        tokens += int((llm.last_usage or {}).get("total_tokens") or 0)
        c_iso, c_op = p_iso or l_iso, p_op or l_op
        stat["n"] += 1
        stat["p_iso"] += p_iso == exp_iso
        stat["l_iso"] += l_iso == exp_iso
        stat["c_iso"] += c_iso == exp_iso
        if exp_op:
            stat["op_n"] += 1
            stat["p_op"] += p_op == exp_op
            stat["l_op"] += l_op == exp_op
            stat["c_op"] += c_op == exp_op
        rows.append({"set": it.get("set", ""), "query": q, "exp_iso": exp_iso, "parser_iso": p_iso, "llm_iso": l_iso, "exp_op": exp_op,
                     "parser_op": p_op, "llm_op": l_op, "sec": round(dt, 2), "error": err})
    n, on = stat["n"], max(stat["op_n"], 1)
    pct = lambda a, b: f"{a}/{b} ({100 * a // max(b, 1)}%)"  # noqa: E731
    print(f"{'':28}{'парсер':>14}{'LLM сама':>14}{'парсер+LLM':>14}")
    print(f"{'группа ISO материала':28}{pct(stat['p_iso'], n):>14}{pct(stat['l_iso'], n):>14}{pct(stat['c_iso'], n):>14}")
    print(f"{'вид обработки':28}{pct(stat['p_op'], on):>14}{pct(stat['l_op'], on):>14}{pct(stat['c_op'], on):>14}")
    lat_sorted = sorted(lat)
    print(f"\nответ не JSON: {stat['bad_json']} | ошибок API: {stat['api_err']} | задержка: средняя {statistics.mean(lat):.1f} с, "
          f"p95 {lat_sorted[int(0.95 * (len(lat_sorted) - 1))]:.1f} с | токенов всего: {tokens or 'провайдер не сообщает'}")
    if tokens:
        print(f"среднее токенов на запрос: {tokens // n} (для расчёта стоимости по тарифу провайдера)")
    with open("data/eval_llm_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nПо строкам: data/eval_llm_report.csv")


if __name__ == "__main__":
    main()
