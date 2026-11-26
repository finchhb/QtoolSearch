import json, subprocess, sys
sys.path.insert(0,'.')
from src import iso1832 as I
PHP=r"C:/Users/Semkin/Documents/Qoder/2026-11-12/5c7e8f1a/tools/php/php.exe"
texts=['CNMG 120408','CNMG120408','снмг 1204O8','CNMG120408PM4325','пластина ромб 09 радиус 02','пластина. Ромб. Размер 09.радиус 02','круглая 08 M0','R08','CNMG120408 10шт; DDJNR2020K1504 2шт','CNMG120408 x5','ромб 80','треугольник 60','квадрат','пластина под нержавейку чистовая','WNMG080408','APMT160408PDER','CCGT09T302','диаметр 12.7','размер 09','12 мм','9 мм','ромб 12','VCMT160404','TNMG160408','задний угол 7','негативная','позитивная','радиус 0.4','r02','CNMG 120408 5 шт','пластина треугольная размер 16 радиус 08','']
def norm(x):
    if isinstance(x,dict): return {k:norm(v) for k,v in x.items()}
    if isinstance(x,list): return [norm(v) for v in x] if x else []
    if isinstance(x,tuple): return [norm(v) for v in x]
    return x
r=subprocess.run([PHP,'php/tests/_iso1832_probe.php'],input=json.dumps({'texts':texts}),capture_output=True,text=True,encoding='utf-8')
if r.returncode!=0: print("PHP ERR",r.stderr[:2000]); sys.exit(1)
php=json.loads(r.stdout)
funcs={'detect_all':I.detect_all,'find_codes':I.find_codes,'split':I.split_positions,'shape':I.detect_shape,'clearance':I.detect_clearance,'radius':I.detect_radius,'size':I.detect_size}
total=0; bad=0
for key,fn in funcs.items():
    for i,t in enumerate(texts):
        a=norm(fn(t)); b=norm(php[key][i]); total+=1
        if a!=b:
            bad+=1
            if bad<=12:
                print("MISMATCH",key,repr(t))
                print("  PY =",json.dumps(a,ensure_ascii=False))
                print("  PHP=",json.dumps(b,ensure_ascii=False))
print("comparisons",total,"mismatches",bad)
