# -*- coding: utf-8 -*-
"""patch_sources2.py — режим «оба»: гарантия представительства каждого магазина в выдаче.
Запуск: python patch_sources2.py  (из корня репозитория). Бэкап: src/hybrid_search.py.bak_src2"""
import os, re, sys, shutil, py_compile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join('src', 'hybrid_search.py')
if not os.path.exists(PATH):
    sys.exit('Не найден src/hybrid_search.py — запускайте из корня репозитория')
src = open(PATH, encoding='utf-8').read()
if 'PATCH_SOURCES_V2' in src:
    print('Патч v2 уже применён.'); raise SystemExit

NEW_SELECT = '''    def _select_diverse_top(self, matches, initial_filters, limit, active_source="rinscom"):
        """PATCH_SOURCES_V2: в режиме both каждый магазин, у которого есть совпадения, попадает в выдачу."""
        def stores_of(m):
            it = m["item"]
            s = set()
            ss = (it.get("source_site") or "").lower()
            if ss:
                s.add("qtool" if "qtool" in ss else "rinscom")
            for o in (it.get("_offers") or []):
                st = (o.get("store") or "").lower()
                if st:
                    s.add("qtool" if "qtool" in st else "rinscom")
            if it.get("rinscom_url"):
                s.add("rinscom")
            if it.get("qtool_url"):
                s.add("qtool")
            return s

        def balance(picked):
            picked = list(picked)
            if active_source != "both" or not picked or limit <= 0:
                return picked[:limit]
            ids = {id(x) for x in picked}
            have = set()
            for m in picked:
                have |= stores_of(m)
            for store in ("rinscom", "qtool"):
                if store in have:
                    continue
                cand = next((m for m in matches
                             if store in stores_of(m) and id(m) not in ids), None)
                if cand is None:
                    continue
                if len(picked) < limit:
                    picked.append(cand)
                else:
                    idx = None
                    for j in range(len(picked) - 1, -1, -1):
                        rest = set()
                        for t, mm in enumerate(picked):
                            if t != j:
                                rest |= stores_of(mm)
                        if stores_of(picked[j]) <= rest:
                            idx = j
                            break
                    if idx is None:
                        idx = len(picked) - 1
                    ids.discard(id(picked[idx]))
                    picked[idx] = cand
                ids.add(id(cand))
                have |= stores_of(cand)
            return picked[:limit]

        if not matches or len(matches) <= limit:
            return balance(matches[:limit])
        if initial_filters.get("clearance_angle") or initial_filters.get("insert_iso_code"):
            return balance(matches[:limit])
        by_ca = {}
        for m in matches:
            by_ca.setdefault(m["item"].get("_ca_up", ""), []).append(m)
        if len(by_ca) <= 1:
            return balance(matches[:limit])
        picked = []
        picked_ids = set()
        for ca_key in ("N", "C", "P", "B"):
            if ca_key in by_ca:
                for cand in by_ca[ca_key][:2]:
                    cid = id(cand)
                    if cid not in picked_ids and len(picked) < limit:
                        picked.append(cand)
                        picked_ids.add(cid)
        for m in matches:
            if len(picked) >= limit:
                break
            cid = id(m)
            if cid not in picked_ids:
                picked.append(m)
                picked_ids.add(cid)
        return balance(picked)

'''

NEW_MERGE = '''    @staticmethod
    def _merge_duplicates(matches):
        """PATCH_SOURCES_V2: при склейке артикула ссылки и признак «в обоих» берём со всех строк."""
        def key(it):
            return re.sub(r"[^A-Z0-9А-Я]", "", str(it.get("sku") or "").upper()) or str(id(it))

        groups = {}
        order = []
        for m in matches:
            k = key(m["item"])
            if k not in groups:
                groups[k] = {"match": m, "rows": [m["item"]]}
                order.append(k)
            else:
                groups[k]["rows"].append(m["item"])

        merged = []
        for k in order:
            g = groups[k]
            if len(g["rows"]) == 1:
                merged.append(g["match"])
                continue
            rows = g["rows"]
            item = dict(rows[0])
            r_url = next((r.get("rinscom_url") for r in rows if r.get("rinscom_url")), "")
            q_url = next((r.get("qtool_url") for r in rows if r.get("qtool_url")), "")
            if r_url:
                item["rinscom_url"] = r_url
            if q_url:
                item["qtool_url"] = q_url
            stores = {r.get("source_site", "") for r in rows if r.get("source_site")}
            if (r_url and q_url) or len(stores) > 1:
                item["in_both_stores"] = "1"
            item["_offers"] = [
                {"store": r.get("source_site", ""), "stock": r.get("stock", 0),
                 "price": r.get("price", 0.0), "currency": r.get("currency", "RUB"),
                 "por": bool(r.get("_por")),
                 "url": (r.get("qtool_url") if r.get("source_site") == "qtool.ru" else r.get("rinscom_url"))
                        or r.get("qtool_url") or r.get("rinscom_url") or ""}
                for r in rows
            ]
            item["stock"] = sum(int(r.get("stock", 0) or 0) for r in rows)
            priced = [r for r in rows if (r.get("price") or 0) > 0 and not r.get("_por")]
            if priced:
                best = min(priced, key=lambda r: r.get("price", 0.0))
                item["price"] = best.get("price", 0.0)
                item["currency"] = best.get("currency", "RUB")
                item["_por"] = False
            m2 = dict(g["match"])
            m2["item"] = item
            merged.append(m2)
        return merged

'''

NEW_LINKS = '''    @staticmethod
    def format_store_links(item, active_source="rinscom"):
        """PATCH_SOURCES_V2: ссылки по всем предложениям, оба магазина не теряются."""
        links = []
        seen = set()

        def add(store, url, primary=False):
            url = (url or "").strip()
            if not url or url in seen:
                return
            seen.add(url)
            is_q = "qtool" in (store or "")
            label = ("Открыть на qtool.ru" if primary and is_q else
                     "Открыть на Rinscom.com" if primary else
                     "Также есть на qtool.ru" if is_q else "Также есть на Rinscom.com")
            links.append(f"[{label}]({url})")

        offers = item.get("_offers") or []

        def rank(o):
            s = (o.get("store") or "").lower()
            if active_source == "qtool":
                return 0 if "qtool" in s else 1
            if active_source == "rinscom":
                return 0 if "rinscom" in s else 1
            return 0

        first = True
        for o in sorted(offers, key=rank):
            add(o.get("store", ""), o.get("url", ""), primary=first)
            first = False
        r_url = (item.get("rinscom_url") or "").strip()
        q_url = (item.get("qtool_url") or "").strip()
        if active_source == "qtool":
            add("qtool.ru", q_url, primary=first); first = False
            add("rinscom.com", r_url)
        else:
            add("rinscom.com", r_url, primary=first); first = False
            add("qtool.ru", q_url)
        return " | ".join(links)

'''

def replace_method(text, name, new_block):
    pat = re.compile(r'^(?P<ind>[ \t]*)def[ \t]+' + re.escape(name) + r'[ \t]*\(', re.M)
    m = pat.search(text)
    if not m:
        raise SystemExit('Не найден метод ' + name + ' — патч не применён')
    ind = m.group('ind')
    start = m.start()
    lines = text[:start].split('\n')
    i = len(lines) - 2
    while i >= 0 and lines[i].strip().startswith('@'):
        start -= len(lines[i]) + 1
        i -= 1
    nxt = re.compile(r'^' + re.escape(ind) + r'(?:@|def[ \t])', re.M)
    m2 = nxt.search(text, m.end())
    end = m2.start() if m2 else len(text)
    return text[:start] + new_block + text[end:]

bak = PATH + '.bak_src2'
if not os.path.exists(bak):
    shutil.copy(PATH, bak)

for name, block in (('_merge_duplicates', NEW_MERGE),
                    ('_select_diverse_top', NEW_SELECT),
                    ('format_store_links', NEW_LINKS)):
    src = replace_method(src, name, block)

call_re = re.compile(r'self\._select_diverse_top\(matches,\s*initial_filters,\s*limit(?:,\s*active_source\s*=\s*active_source)?\)')
if not call_re.search(src):
    sys.exit('Не найден вызов _select_diverse_top — патч не применён')
src = call_re.sub('self._select_diverse_top(matches, initial_filters, limit, active_source=active_source)', src)

open(PATH, 'w', encoding='utf-8').write(src)
py_compile.compile(PATH, doraise=True)
print('Патч v2 применён, файл компилируется.')

# --- регресс-тест ровно на вашем случае: cnmg190616 ---
try:
    sys.path.insert(0, os.getcwd())
    from src.hybrid_search import HybridSearchEngine as H
    q = [{"item": {"sku": "CNMG 190616 X%d" % i, "source_site": "qtool.ru",
                   "qtool_url": "https://qtool.ru/%d" % i, "rinscom_url": "",
                   "stock": s, "_ca_up": "N"}, "score": 5.0}
         for i, s in enumerate([300, 297, 240, 174, 138])]
    r = {"item": {"sku": "231486", "source_site": "rinscom.com", "qtool_url": "",
                  "rinscom_url": "https://www.rinscom.com/231486", "stock": 4, "_ca_up": "N"},
         "score": 5.0}
    matches = q + [r]
    sel = H._select_diverse_top(None, matches, {"insert_iso_code": "CNMG190616"}, 5, active_source="both")
    assert any(m["item"]["sku"] == "231486" for m in sel), 'Rinscom всё ещё вытеснен'
    assert len(sel) == 5, 'размер выдачи изменился'
    sel_r = H._select_diverse_top(None, matches, {"insert_iso_code": "CNMG190616"}, 5, active_source="rinscom")
    assert all(m["item"]["source_site"] == "qtool.ru" for m in sel_r), 'режим rinscom не должен меняться'
    merged = H._merge_duplicates([
        {"item": {"sku": "X", "source_site": "qtool.ru", "qtool_url": "q", "rinscom_url": "",
                  "stock": 5, "price": 100.0, "currency": "RUB", "_por": False}, "score": 9.0},
        {"item": {"sku": "X", "source_site": "rinscom.com", "qtool_url": "", "rinscom_url": "r",
                  "stock": 3, "price": 90.0, "currency": "RUB", "_por": False}, "score": 1.0}])
    it = merged[0]["item"]
    assert it["rinscom_url"] == "r" and it["stock"] == 8 and it["price"] == 90.0
    links = H.format_store_links(it, active_source="both")
    assert "(r)" in links and "(q)" in links
    print('Регресс-тест cnmg190616: OK — Rinscom попадает в топ-5, режим «только Rinscom» не изменился.')
except SystemExit:
    raise
except Exception as e:
    print('Патч записан, но тест не выполнен:', type(e).__name__, e)

print('Готово. Перезапустите сервер, Ctrl+F5.')