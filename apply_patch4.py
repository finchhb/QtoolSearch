import re
import ast
from pathlib import Path

SRC = Path("src")
p = SRC / "catalog_search.py"
t = p.read_text(encoding="utf-8")
changed = False

# --- 2a) module-level helpers ---
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
    changed = True
    print("2a: helpers inserted")

# --- 2b-1) search() call ---
if "# EXACT_SKU_LOOKUP" not in t:
    search_anchor = "        q = Query(text, self._insert_prefixes, self._by_family_and_code)\n"
    if t.count(search_anchor) != 1:
        raise SystemExit(f"search_anchor count={t.count(search_anchor)}")
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
    changed = True
    print("2b-1: search call inserted")

# --- 2b-2) _try_exact_lookup method ---
if "def _try_exact_lookup" not in t:
    m = re.search(r"\n([ \t]+)def _ask_params\b", t)
    if not m:
        raise SystemExit("Cannot locate _ask_params")
    indent = m.group(1)
    body = indent + "    "
    method = (
        f"{indent}def _try_exact_lookup(self, q) -> Optional[Dict[str, Any]]:\n"
        f"{body}\"\"\"Exact match by sku / id / attrs[manufacturer_code] / attrs[article].\"\"\"\n"
        f"{body}toks = [x for x in (getattr(q, \"free_tokens\", None) or []) if x]\n"
        f"{body}if not toks:\n"
        f"{body}    return None\n"
        f"{body}hits, seen = [], set()\n"
        f"{body}for tok in toks:\n"
        f"{body}    want = _norm_code(tok)\n"
        f"{body}    if len(want) < 4 or not re.search(r\"\\d\", want):\n"
        f"{body}        continue\n"
        f"{body}    for it in self.items:\n"
        f"{body}        a = it.get(\"attrs\") or {{}}\n"
        f"{body}        keys = (\n"
        f"{body}            _norm_code(it.get(\"sku\", \"\")),\n"
        f"{body}            _norm_code(it.get(\"id\", \"\")),\n"
        f"{body}            _norm_code(a.get(\"manufacturer_code\", \"\")),\n"
        f"{body}            _norm_code(a.get(\"article\", \"\")),\n"
        f"{body}        )\n"
        f"{body}        if want in keys and id(it) not in seen:\n"
        f"{body}            seen.add(id(it))\n"
        f"{body}            hits.append(it)\n"
        f"{body}if not hits:\n"
        f"{body}    return None\n"
        f"{body}fam = hits[0].get(\"family\") or None\n"
        f"{body}cards = [self._card(it, 1.0, q) for it in hits[:8]]\n"
        f"{body}return {{\n"
        f"{body}    \"query\": q.text, \"family\": fam, \"groups\": [],\n"
        f"{body}    \"products\": cards, \"parsed\": dict(q.attrs),\n"
        f"{body}    \"chips\": self._chips(q, fam), \"level\": \"exact\",\n"
        f"{body}    \"total_found\": len(hits), \"relaxations\": [],\n"
        f"{body}    \"follow_ups\": [], \"note\": \"\",\n"
        f"{body}}}\n"
        f"\n"
    )
    t = t[:m.start() + 1] + method + t[m.start() + 1:]
    changed = True
    print(f"2b-2: _try_exact_lookup inserted (indent={len(indent)})")

# --- 2c) family filter in _search_family ---
if "# FAMILY_TOKEN_FILTER" not in t:
    fam_anchor = "        pool = self.by_family.get(fam, [])\n        if not pool:\n            pool = self._related_pool(fam)\n"
    if t.count(fam_anchor) == 1:
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
        changed = True
        print("2c: family filter inserted")
    else:
        print(f"2c WARNING: fam_anchor count={t.count(fam_anchor)} — skipped")

if not changed:
    print("\nNo changes — file already patched.")
else:
    try:
        ast.parse(t)
    except SyntaxError as e:
        raise SystemExit(f"ABORT — syntax error after patch, file NOT written: {e}")
    p.write_text(t, encoding="utf-8")
    print(f"\nWritten catalog_search.py ({len(t)} bytes)")