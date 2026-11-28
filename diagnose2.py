# diagnose2.py
import re
from pathlib import Path

def dump(name, path, count=40):
    t = Path(path).read_text(encoding="utf-8")
    m = re.search(rf"    def {name}\(self.*?(?=\n    def )", t, re.S)
    if not m:
        print(f"[{path}] {name} — не найдено"); return
    print(f"\n--- {path}:{name} (первые {count} строк) ---")
    for j, ln in enumerate(m.group(0).splitlines()[:count], 1):
        print(f"{j:3d}: {ln}")

dump("search", "src/catalog_search.py", 40)
dump("_search_family", "src/catalog_search.py", 30)

t = Path("src/iso5608.py").read_text(encoding="utf-8")
print("\n--- iso5608.py: все def и константы ---")
for i, ln in enumerate(t.splitlines(), 1):
    if re.match(r"\s*(def\s+\w+|class\s+\w+|[A-Z_]{3,}\s*=)", ln):
        print(f"{i:5d}: {ln.strip()}")
m = re.search(r"def parse_holder_code\(.*?(?=\ndef |\nclass |\Z)", t, re.S)
if m:
    print("\n--- iso5608.py: parse_holder_code ---")
    print(m.group(0)[:5000])