# -*- coding: utf-8 -*-
"""patch_sources.py — режим «оба»: не терять позиции и ссылки Rinscom.
Запуск: python patch_sources.py   (из корня репозитория)
Бэкап: src/hybrid_search.py.bak_sources
Повторный запуск безопасен."""
import os, re, sys, shutil, py_compile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join('src', 'hybrid_search.py')
if not os.path.exists(PATH):
    sys.exit('Не найден src/hybrid_search.py — запускайте из корня репозитория')

src = open(PATH, encoding='utf-8').read()
if 'PATCH_SOURCES_V1' in src:
    print('Патч уже применён. Ничего не делаю.'); raise SystemExit

NEW_MERGE = '''    @staticmethod
    def _merge_duplicates(matches):
        """PATCH_SOURCES_V1: склейка артикула; ссылки и магазины берём со ВСЕХ строк."""
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

NEW_SELECT = '''    def _select_diverse_top(self, matches, initial_filters, limit, active_source="rinscom"):
        """PATCH_SOURCES_V1: в режиме both гарантируем место позиции с наличием Rinscom."""
        def has_rinscom(m):
            it = m["item"]
            if it.get("rinscom_url"):
                return True
            return any("rinscom" in (o.get("store") or "") for o in (it.get("_offers") or []))

        def guarantee(picked):
            picked = list(picked)
            if active_source != "both" or not picked:
                return picked[:limit]
            if any(has_rinscom(m) for m in picked):
                return picked[:limit]
            cand = next((m for m in matches if has_rinscom(m)), None)
            if cand is None:
                return picked[:limit]
            if len(picked) >= limit:
                picked = picked[:-1] + [cand]
            else:
                picked = picked + [cand]
            return picked[:limit]

        if not matches or len(matches) <= limit:
            return guarantee(matches[:limit])
        if initial_filters.get("clearance_angle") or initial_filters.get("insert_iso_code"):
            return guarantee(matches[:limit])
        by_ca = {}
        for m in matches:
            by_ca.setdefault(m["item"].get("_ca_up", ""), []).append(m)
        if len(by_ca) <= 1:
            return guarantee(matches[:limit])
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
        return guarantee(picked)

'''

NEW_LINKS = '''    @staticmethod
    def format_store_links(item, active_source="rinscom"):
        """PATCH_SOURCES_V1: ссылки строятся по всем предложениям (_offers)."""
        links = []
        seen = set()

        def add(store, url):
            url = (url or "").strip()
            if not url or url in seen:
                return
            seen.add(url)
            label = "qtool.ru" if "qtool" in (store or "") else "Rinscom.com"
            links.append(f"[{label}]({url})")

        offers = item.get("_offers") or []

        def rank(o):
            s = o.get("store", "") or ""
            if active_source == "qtool":
                return 0 if "qtool" in s else 1
            if active_source == "rinscom":
                return 0 if "rinscom" in s else 1
            return 0

        for o in sorted(offers, key=rank):
            add(o.get("store", ""), o.get("url", ""))
        r_url = (item.get("rinscom_url") or "").strip()
        q_url = (item.get("qtool_url") or "").strip()
        if active_source == "qtool":
            add("qtool.ru", q_url)
            add("rinscom.com", r_url)
        else:
            add("rinscom.com", r_url)
            add("qtool.ru", q_url)
        return " | ".join(links)

'''

def replace_method(text, name, new_block):
    """Заменяет метод целиком (вместе с декоратором) до следующего def того же уровня."""
    pat = re.compile(r'^(?P<ind>[ \t]*)def[ \t]+' + re.escape(name) + r'[ \t]*\(', re.M)
    m = pat.search(text)
    if not m:
        raise SystemExit('Не найден метод ' + name + ' — файл отличается, патч не применён')
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

bak = PATH + '.bak_sources'
if not os.path.exists(bak):
    shutil.copy(PATH, bak)

for name, block in (('_merge_duplicates', NEW_MERGE),
                    ('_select_diverse_top', NEW_SELECT),
                    ('format_store_links', NEW_LINKS)):
    src = replace_method(src, name, block)

old_call = 'self._select_diverse_top(matches, initial_filters, limit)'
new_call = 'self._select_diverse_top(matches, initial_filters, limit, active_source=active_source)'
if src.count(old_call) != 1:
    sys.exit('Не найдена строка вызова _select_diverse_top — патч не применён')
src = src.replace(old_call, new_call)

open(PATH, 'w', encoding='utf-8').write(src)
py_compile.compile(PATH, doraise=True)
print('Патч применён, файл компилируется.')

# --- смоук-тест на искусственных строках (каталог не нужен) ---
try:
    sys.path.insert(0, os.getcwd())
    from src.hybrid_search import HybridSearchEngine as H
    q = {"sku": "X1", "source_site": "qtool.ru", "qtool_url": "https://qtool.ru/x", "rinscom_url": "",
         "stock": 5, "price": 100.0, "currency": "RUB", "_por": False, "_ca_up": "N"}
    r = {"sku": "X1", "source_site": "rinscom.com", "qtool_url": "", "rinscom_url": "https://www.rinscom.com/x",
         "stock": 3, "price": 90.0, "currency": "RUB", "_por": False, "_ca_up": "N"}
    merged = H._merge_duplicates([{"item": q, "score": 9.0}, {"item": r, "score": 1.0}])
    it = merged[0]["item"]
    assert it["rinscom_url"] and it["qtool_url"], 'ссылки не объединились'
    assert it["stock"] == 8 and it["price"] == 90.0, 'остаток/цена не агрегированы'
    links = H.format_store_links(it, active_source="both")
    assert "rinscom.com/x" in links and "qtool.ru/x" in links, 'в ссылках нет обоих магазинов'
    top = [{"item": {"sku": "Q%d" % i, "_ca_up": "N", "rinscom_url": "", "qtool_url": "u"}, "score": 10 - i}
           for i in range(5)]
    low = {"item": {"sku": "R", "_ca_up": "N", "rinscom_url": "r", "qtool_url": ""}, "score": 0.1}
    sel = H._select_diverse_top(None, top + [low], {}, 5, active_source="both")
    assert any(m["item"]["sku"] == "R" for m in sel), 'гарантия Rinscom не сработала'
    print('Смоук-тест: OK (ссылки, остаток, цена, гарантия Rinscom).')
except SystemExit:
    raise
except Exception as e:
    print('Патч записан, но смоук-тест не выполнен:', type(e).__name__, e)

print('Готово. Перезапустите сервер и обновите страницу Ctrl+F5.')