import re
import ast
from pathlib import Path

p = Path("src/catalog_search.py")
t = p.read_text(encoding="utf-8")

# ---- Fix 1: _family_tokens_from_query — не трогать запросы, где код уже распознан,
#            и не считать insert-префиксы (DCGT, CNMG) семействами ----
old_fn = '''def _family_tokens_from_query(q) -> list:
    """Family tokens like SCLCR09 that are NOT valid ISO codes."""
    out = []
    candidates = list(getattr(q, "free_tokens", []) or [])
    for attr in ("holder_code", "insert_code"):
        v = getattr(q, attr, None)
        if v:
            candidates.append(v)
    for tok in candidates:
        m = _FAMILY_CODE_RE.match(str(tok or "").strip())
        if not m:
            continue
        base = f"{m.group(1).upper()}{m.group(2)}"
        try:
            if parse_holder_code(base):
                continue
            if _extract_insert_code(base):
                continue
        except Exception:
            pass
        if base not in out:
            out.append(base)
    return out
'''
new_fn = '''def _family_tokens_from_query(q) -> list:
    """Family tokens like SCLCR09 that are NOT valid ISO codes."""
    if getattr(q, "holder_code", None) or getattr(q, "insert_code", None):
        return []
    out = []
    for tok in list(getattr(q, "free_tokens", []) or []):
        m = _FAMILY_CODE_RE.match(str(tok or "").strip())
        if not m:
            continue
        prefix = m.group(1).upper()
        base = f"{prefix}{m.group(2)}"
        try:
            if insert_prefix_from_word(prefix):
                continue
            if parse_holder_code(base):
                continue
            if _extract_insert_code(base):
                continue
        except Exception:
            pass
        if base not in out:
            out.append(base)
    return out
'''
if old_fn in t:
    t = t.replace(old_fn, new_fn)
    print("fix1: _family_tokens_from_query replaced")
elif new_fn in t:
    print("fix1: already applied")
else:
    raise SystemExit("fix1: pattern not found")

# ---- Fix 2: _try_exact_lookup — bail out if parser already found a code ----
old_anchor = '''    def _try_exact_lookup(self, q) -> Optional[Dict[str, Any]]:
        """Exact match by sku / id / attrs[manufacturer_code] / attrs[article]."""
        toks = [x for x in (getattr(q, "free_tokens", None) or []) if x]
        if not toks:
            return None
'''
new_anchor = '''    def _try_exact_lookup(self, q) -> Optional[Dict[str, Any]]:
        """Exact match by sku / id / attrs[manufacturer_code] / attrs[article]."""
        if getattr(q, "insert_code", None) or getattr(q, "holder_code", None):
            return None
        toks = [x for x in (getattr(q, "free_tokens", None) or []) if x]
        if not toks:
            return None
'''
if old_anchor in t:
    t = t.replace(old_anchor, new_anchor)
    print("fix2: _try_exact_lookup guard added")
elif new_anchor in t:
    print("fix2: already applied")
else:
    raise SystemExit("fix2: pattern not found")

# ---- Fix 3: family-filter не должен обнулять insert_code / holder_code ----
old_filter = '''        # FAMILY_TOKEN_FILTER: SCLCR09 etc. — narrow pool by substring in name
        _ftoks = getattr(q, "_family_tokens", None) or []
        if _ftoks and fam in ("holder", "insert", "mill"):
            _narrowed = [it for it in pool if any(
                ft in _norm_code(it.get("name", "")) for ft in _ftoks)]
            if _narrowed:
                pool = _narrowed
                q.holder_code = None
                q.insert_code = None
'''
new_filter = '''        # FAMILY_TOKEN_FILTER: SCLCR09 etc. — narrow pool by substring in name
        _ftoks = getattr(q, "_family_tokens", None) or []
        if _ftoks and fam in ("holder", "insert", "mill"):
            _narrowed = [it for it in pool if any(
                ft in _norm_code(it.get("name", "")) for ft in _ftoks)]
            if _narrowed:
                pool = _narrowed
'''
if old_filter in t:
    t = t.replace(old_filter, new_filter)
    print("fix3: family filter — code-clear removed")
elif new_filter in t:
    print("fix3: already applied")
else:
    raise SystemExit("fix3: pattern not found")

# validate
try:
    ast.parse(t)
except SyntaxError as e:
    raise SystemExit(f"ABORT: {e}")

p.write_text(t, encoding="utf-8")
print(f"\nWritten catalog_search.py ({len(t)} bytes)")