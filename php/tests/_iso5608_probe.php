<?php
require __DIR__ . '/../src/Autoload.php';
$codes = json_decode(file_get_contents('php://stdin'), true);
$out = [];
foreach ($codes as $c) { $out[] = Qtool\Iso5608::parseHolderCode($c); }
echo json_encode($out, JSON_UNESCAPED_UNICODE);
