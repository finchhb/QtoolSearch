# apply_patch2.py
import shutil
from pathlib import Path

SRC = Path("src")
BK = Path("src_backup_before_patch")

# 0) Восстановить iso5608.py из бэкапа (предыдущий патч его сломал)
if (BK / "iso5608.py").exists():
    shutil.copy(BK / "iso5608.py", SRC / "iso5608.py")
    print("iso5608.py: восстановлен из бэкапа")

# 1) site_catalog.py — article/manufacturer_code в attrs внутри parse_attrs
p = SRC / "site_catalog.py"
t = p.read_text(encoding="utf-8")
anchor = '    return {k: v for k, v in a.items() if v not in (None, "", [])}\n'
assert t.count(anchor) == 1, f"anchor count: {t.count(anchor)}"
inject = (
    '    if cols:\n'
    '        for k, v in cols.items():\n'
    '            kl = (k or "").lower().strip()\n'
    '            if not v:\n'
    '                continue\n'
    '            if "\u0430\u0440\u0442\u0438\u043a\u0443\u043b" in kl and "article" not in a:\n'
    '                a["article"] = v.strip()\n'
    '            if "\u043a\u043e\u0434 \u043f\u0440\u043e\u0438\u0437\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044f" in kl and "manufacturer_code" not in a:\n'
    '                a["manufacturer_code"] = v.strip()\n'
)
t = t.replace(anchor, inject + anchor)
p.write_text(t, encoding="utf-8")
print("site_catalog.py: article / manufacturer_code добавлены в attrs")