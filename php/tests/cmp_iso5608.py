import json, subprocess, sys
sys.path.insert(0,'.')
from src.iso5608 import parse_holder_code
PHP=r"C:/Users/Semkin/Documents/Qoder/2026-11-12/5c7e8f1a/tools/php/php.exe"
codes=['DCLNR 2525M-12-M-A','DCLNR2525M12','MCLNR2525M12','MCLNL1616H12','CKJNL2525M16','SCLCR2525M12','SCLCR1616H09','S16Q-SCLCR09','S16Q-SCLCR-09-M-A','S25S-2MWN08-33','C06K-SCLCR06','S16Q-KGIR-3','SNR0006K06-A12','SER2525M16','SEL2525M16','SNR0006K06','SCVER2525M16','CTTR2525M16','KGFH2020-26','KGFH26-2-M','KGFDL2020K-2535-3-M','KGDR2525M-3T20-M','MGEHR2020-3C','MGIVR2016-1.5','TTER2525-3','QEKS2020K-16','CGBL2525M-03','KTGFR2525M-03','GQCR2525M-03','HNGR08J07','FGHH','EWB1608-32','DDJNR2020K1504','MTJNR2525M16','PCLNR2525M12','зсдтк2525м12','сслкр2525м12','CNMG120408','APMT1604','BT50-SLN25-100','SBHA32','ER32','пластина','державка','SCLCR09','2525','']
def norm(x):
    if isinstance(x,dict): return {k:norm(v) for k,v in x.items()}
    if isinstance(x,list): return [norm(v) for v in x] if x else {}
    return x
r=subprocess.run([PHP,'php/tests/_iso5608_probe.php'],input=json.dumps(codes),capture_output=True,text=True,encoding='utf-8')
if r.returncode!=0:
    print("PHP ERR",r.stderr); sys.exit(1)
php=json.loads(r.stdout)
bad=0
for c,b in zip(codes,php):
    a=parse_holder_code(c)
    if norm(a)!=norm(b):
        bad+=1
        if bad<=8:
            print("MISMATCH",repr(c))
            print("  PY =",json.dumps(a,ensure_ascii=False))
            print("  PHP=",json.dumps(b,ensure_ascii=False))
print("codes",len(codes),"mismatches",bad)
