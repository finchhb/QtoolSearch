import json, subprocess, sys
sys.path.insert(0,'.')
from src.site_catalog import load_site_catalog
PHP=r"C:/Users/Semkin/Documents/Qoder/2026-11-12/5c7e8f1a/tools/php/php.exe"
items=load_site_catalog()
by={}
for it in items:
    by.setdefault(it['sku'],it)
# pick diverse sample
import random
random.seed(7)
sample=random.sample(items, 40)
skus=[it['sku'] for it in sample]
probe='<?php require __DIR__."/../src/Autoload.php"; $s=new Qtool\Storage(); $items=$s->loadCatalogItems(); $want=json_decode(file_get_contents("php://stdin"),true); $by=[]; foreach($items as $it){$by[$it["sku"]]=$it;} $out=[]; foreach($want as $sku){$out[]=$by[$sku]??null;} echo json_encode($out,JSON_UNESCAPED_UNICODE);'
open('php/tests/_cat_probe.php','w',encoding='utf-8').write(probe)
r=subprocess.run([PHP,'php/tests/_cat_probe.php'],input=json.dumps(skus),capture_output=True,text=True,encoding='utf-8')
php=json.loads(r.stdout)
bad=0
for a,b in zip(sample,php):
    if a!=b:
        bad+=1
        if bad<=5:
            print("MISMATCH sku=",a['sku'])
            for k in a:
                if a[k]!=b.get(k): print("   ",k,"PY=",repr(a[k]),"PHP=",repr(b.get(k)))
print("sample",len(sample),"mismatches",bad)
print("total PY items",len(items))

def norm(x):
    if isinstance(x,list): return [norm(v) for v in x]
    if isinstance(x,dict): return {k:norm(v) for k,v in x.items()}
    return x
def empt(x):
    # php empty array -> python empty dict equivalence
    if isinstance(x,dict): return {k:empt(v) for k,v in x.items()}
    if isinstance(x,list): return [empt(v) for v in x] if x else {}
    return x
bad2=0
for a,b in zip(sample,php):
    if empt(norm(a))!=empt(norm(b)):
        bad2+=1
        if bad2<=5:
            print("REAL MISMATCH",a['sku'])
            for k in a:
                if empt(norm(a[k]))!=empt(norm(b.get(k))): print("   ",k,repr(a[k]),repr(b.get(k)))
print("after empty-normalization mismatches:",bad2)
