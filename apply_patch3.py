import re
import shutil
from pathlib import Path

SRC = Path("src")
BK = Path("src_backup_before_patch")

# 0) Восстановить iso5608.py из бэкапа (первый патч его сломал)
if (BK / "iso5608.py").exists():
    shutil.copy(BK / "iso5608.py", SRC / "iso5608.py")
    print("iso5608.py: восстановлен из бэкапа")

# 1) site_catalog.py
p = SRC / "site_catalog.py"
t = p.read_text(encoding="utf-8")
anchor = '    return {k: v for k, v in a.items() if v not in (None, "", [])}\n'

if "MANUFACTURER_CODE_FROM_COLS" not in t:
    inject = (
        '    # MANUFACTURER_CODE_FROM_COLS\n'
        '    if cols:\n'
        '        for _k, _v in cols.items():\n'
        '            _kl = (_k or "").lower().strip()\n'
        '            if not _v:\n'
        '                continue\n'
        '            if ("\u0430\u0440\u0442\u0438\u043a\u0443\u043b" in _kl) and ("article" not in a):\n'
        '                a["article"] = _v.strip()\n'
        '            if ("\u043a\u043e\u0434 \u043f\u0440\u043e\u0438\u0437\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044f" in _kl) and ("manufacturer_code" not in a):\n'
        '                a["manufacturer_code"] = _v.strip()\n'
    )
    assert t.count(anchor) == 1, f"anchor count: {t.count(anchor)}"
    t = t.replace(anchor, inject + anchor)
    p.write_text(t, encoding="utf-8")
    print("site_catalog.py: пропатчен")
else:
    print("site_catalog.py: уже пропатчен")

# 2) catalog_search.py
p = SRC / "catalog_search.py"
t = p.read_text(encoding="utf-8")

# 2a) module-level helpers
if "_FAMILY_CODE_RE" not in t:
    helpers = (
        '\n_FAMILY_CODE_RE = re.compile(r"^([A-Za-z]{4,6})-?(\\d{2,4})$")\n'
        '\n'
        'def _norm_code(s: str) -> str:\n'
        '    return re.sub(r"[\\s\\-_./]+", "", str(s or "").upper())\n'
        '\n'
        'def _family_tokens_from_query(q) -> list:\n'
        '    """Family tokens like SCLCR09 that are NOT valid ISO codes."""\n'
        '    out = []\n'
        '    candidates = list(getattr(q, "free_tokens", []) or [])\n'
        '    for attr in ("holder_code", "insert_code"):\n'
        '        v = getattr(q, attr, None)\n'
        '        if v:\n'
        '            candidates.append(v)\n'
        '    for tok in candidates:\n'
        '        m = _FAMILY_CODE_RE.match(str(tok or "").strip())\n'
        '        if not m:\n'
        '            continue\n'
        '        base = f"{m.group(1).upper()}{m.group(2)}"\n'
        '        try:\n'
        '            if parse_holder_code(base):\n'
        '                continue\n'
        '            if _extract_insert_code(base):\n'
        '                continue\n'
        '        except Exception:\n'
        '            pass\n'
        '        if base not in out:\n'
        '            out.append(base)\n'
        '    return out\n'
    )
    lines = t.splitlines(keepends=True)
    last_imp = 0
    for i, ln in enumerate(lines):
        if re.match(r"^(import |from )", ln):
            last_imp = i
    t = "".join(lines[:last_imp + 1]) + helpers + "\n" + "".join(lines[last_imp + 1:])
    print("catalog_search.py: helpers вставлены")

# 2b) в search() — точный lookup + сбор family-токенов
if "# EXACT_SKU_LOOKUP" not in t:
    search_anchor = "        q = Query(text, self._insert_prefixes, self._by_family_and_code)\n"
    assert t.count(search_anchor) == 1
    exact = (
        '        # EXACT_SKU_LOOKUP\n'
        '        _exact = self._try_exact_lookup(q)\n'
        '        if _exact:\n'
        '            return _exact\n'
        '        q._family_tokens = _family_tokens_from_query(q)\n'
        '        if q._family_tokens and q.family is None:\n'
        '            q.family = "holder"\n'
    )
    t = t.replace(search_anchor, search_anchor + exact)

    method_anchor = "        def _ask_params(self, q: Query) -> Dict[str, Any]:\n"
    assert t.count(method_anchor) == 1
    method = (
        '        def _try_exact_lookup(self, q) -> Optional[Dict[str, Any]]:\n'
        '            """Exact match by sku / id / attrs[manufacturer_code] / attrs[article]."""\n'
        '            toks = [x for x in (getattr(q, "free_tokens", None) or []) if x]\n'
        '            if not toks:\n'
        '                return None\n'
        '            hits, seen = [], set()\n'
        '            for tok in toks:\n'
        '                want = _norm_code(tok)\n'
        '                if len(want) < 4 or not re.search(r"\\d", want):\n'
        '                    continue\n'
        '                for it in self.items:\n'
        '                    a = it.get("attrs") or {}\n'
        '                    keys = (\n'
        '                        _norm_code(it.get("sku", "")),\n'
        '                        _norm_code(it.get("id", "")),\n'
        '                        _norm_code(a.get("manufacturer_code", "")),\n'
        '                        _norm_code(a.get("article", "")),\n'
        '                    )\n'
        '                    if want in keys and id(it) not in seen:\n'
        '                        seen.add(id(it))\n'
        '                        hits.append(it)\n'
        '            if not hits:\n'
        '                return None\n'
        '            fam = hits[0].get("family") or None\n'
        '            cards = [self._card(it, 1.0, q) for it in hits[:8]]\n'
        '            return {\n'
        '                "query": q.text, "family": fam, "groups": [],\n'
        '                "products": cards, "parsed": dict(q.attrs),\n'
        '                "chips": self._chips(q, fam), "level": "exact",\n'
        '                "total_found": len(hits), "relaxations": [],\n'
        '                "follow_ups": [], "note": "",\n'
        '            }\n\n'
    )
    t = t.replace(method_anchor, method + method_anchor)
    print("catalog_search.py: exact lookup вставлен")

# 2c) в _search_family — сужение пула по family-токенам
if "# FAMILY_TOKEN_FILTER" not in t:
    fam_anchor = "        pool = self.by_family.get(fam, [])\n        if not pool:\n            pool = self._related_pool(fam)\n"
    assert t.count(fam_anchor) == 1
    fam_filter = (
        '        pool = self.by_family.get(fam, [])\n'
        '        if not pool:\n'
        '            pool = self._related_pool(fam)\n'
        '        # FAMILY_TOKEN_FILTER: SCLCR09 etc. — narrow pool by substring in name\n'
        '        _ftoks = getattr(q, "_family_tokens", None) or []\n'
        '        if _ftoks and fam in ("holder", "insert", "mill"):\n'
        '            _narrowed = [it for it in pool if any(\n'
        '                ft in _norm_code(it.get("name", "")) for ft in _ftoks)]\n'
        '            if _narrowed:\n'
        '                pool = _narrowed\n'
        '                q.holder_code = None\n'
        '                q.insert_code = None\n'
    )
    t = t.replace(fam_anchor, fam_filter)
    print("catalog_search.py: family-фильтр вставлен")

p.write_text(t, encoding="utf-8")
print("\nГотово.")