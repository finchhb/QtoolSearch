<?php
require __DIR__ . '/../src/Autoload.php';
$in = json_decode(file_get_contents('php://stdin'), true);
$out = [];
foreach ($in['texts'] as $t) {
    $out['detect_all'][] = Qtool\Iso1832::detectAll($t);
    $out['find_codes'][] = Qtool\Iso1832::findCodes($t);
    $out['split'][] = Qtool\Iso1832::splitPositions($t);
    $out['shape'][] = Qtool\Iso1832::detectShape($t);
    $out['clearance'][] = Qtool\Iso1832::detectClearance($t);
    $out['radius'][] = Qtool\Iso1832::detectRadius($t);
    $out['size'][] = Qtool\Iso1832::detectSize($t);
}
echo json_encode($out, JSON_UNESCAPED_UNICODE);
