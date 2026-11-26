<?php
require __DIR__ . '/../src/Autoload.php';
use Qtool\Normalize as N;
$cases = ['CNMG 120408','снмг 1204O8','СТМН 120408','РПМТ1204','MCВNR2525M12','зсдтк2525м12','барпулер','Сверло 8,5 мм','ёлка','CNMG12040B'];
foreach ($cases as $c) {
    echo json_encode([
        'in'=>$c,'compact'=>N::compact($c),'variants'=>N::queryVariants($c),'codevar'=>N::codeVariants($c),
        'layout'=>N::layoutToLatin($c),'homo'=>N::homoglyphLatin($c),'cyr'=>N::cyrillicCodeLetters($c),
        'tok'=>N::tokenize($c),'fix'=>N::fixDigitLetters($c),
    ], JSON_UNESCAPED_UNICODE), "\n";
}
echo "damerau CNMG/CNMG=".N::damerau('CNMG','CNMG')." CNMG/CMMG=".N::damerau('CNMG','CMMG')." CNMG/CNMGX=".N::damerau('CNMG','CNMGX')."\n";
echo "fmt 8.5=".N::fmtNum(8.5)." 90.0=".N::fmtNum(90.0)." 0.2=".N::fmtNum(0.2)."\n";
echo "mat=".N::materialIso('по нержавейке')."/".N::materialIso('титан')."/".N::materialIso('сталь 45')."\n";
