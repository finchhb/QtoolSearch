"""Проверка багов из аудита на живом каталоге."""
from src.catalog_search import CatalogSearchEngine
from src.site_catalog import load_site_catalog

items = load_site_catalog()
e = CatalogSearchEngine(items)


def show(q, n=5):
    r = e.search(q, limit=n)
    print(f"\n=== {q!r} ===")
    print(f"  family={r.get('family')} level={r.get('level')} total={r.get('total_found')}")
    for p in (r.get('products') or [])[:n]:
        print(f"   - {p['sku']:20} | {p['name'][:60]} | stock={p['stock']}")
    if r.get('chips'):
        print(f"   chips: {r['chips']}")
    if r.get('follow_ups'):
        print(f"   follow_ups: {r['follow_ups']}")


# B1: wrong layout for plate code ("стьп120408" = CNMG120408 in Russian layout)
show('стьп120408')

# B2: wrong layout for holder ("зсдтк2525м12" = PCLNR2525M12 in Russian layout)
show('зсдтк2525м12')

# B3: digit typo
show('CNMG12040B')
show('CNMG12048')

# B4: code+grade glue
show('CNMG120408PM4325')

# B5: material for drill
show('сверло по нержавейке 8.5')

# B6: slang
show('фреза кукуруза 16')

# B7: bare number for holder
show('державка расточная 16')

# B8/B9: common word dumps family
show('фреза', n=3)

print("\n--- Проверка разбора запросов (Query) ---")
from src.catalog_search import Query
for q in ('стьп120408', 'зсдтк2525м12', 'державка расточная 16'):
    qq = Query(q)
    print(f"{q!r}: family={qq.family} insert_code={qq.insert_code} holder_code={qq.holder_code} "
          f"attrs={dict(qq.attrs)}")
