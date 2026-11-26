import json, subprocess, sys
sys.path.insert(0, '.')
from src.catalog_search import compact, query_variants, tokenize, _fix_digit_letters, fmt_num, damerau, material_iso
from src.code_normalize import code_variants, layout_to_latin, homoglyph_latin, cyrillic_code_letters
PHP=r"C:/Users/Semkin/Documents/Qoder/2026-11-12/5c7e8f1a/tools/php/php.exe"
cases=['CNMG 120408','снмг 1204O8','СТМН 120408','РПМТ1204','MCВNR2525M12','зсдтк2525м12','барпулер','Сверло 8,5 мм','ёлка','CNMG12040B','державка 2525 под CNMG1204','патрон бт50 под велдон 25 длинной 100']
def py(c): return {'in':c,'compact':compact(c),'variants':query_variants(c),'codevar':code_variants(c),'layout':layout_to_latin(c),'homo':homoglyph_latin(c),'cyr':cyrillic_code_letters(c),'tok':tokenize(c),'fix':_fix_digit_letters(c)}
out=subprocess.run([PHP,'php/tests/norm_probe.php'],capture_output=True,text=True,encoding='utf-8').stdout
php=[json.loads(l) for l in out.splitlines() if l.startswith('{')]
# probe has 10 cases; extend probe to 12 by re-running with extra cases handled separately
bad=0
for i,c in enumerate(cases[:10]):
    a=py(c); b=php[i]
    if a!=b:
        bad+=1; print("MISMATCH",c)
        for k in a:
            if a[k]!=b.get(k): print("  ",k,"PY=",a[k],"PHP=",b.get(k))
print("compared 10 cases, mismatches:",bad)
print("damerau", damerau('CNMG','CMMG'), damerau('пластина','пластена'))
