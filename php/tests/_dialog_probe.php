<?php
require __DIR__ . '/../src/Autoload.php';

use Qtool\Dialog;

$in = json_decode(stream_get_contents(STDIN), true);
$prefixes = [];
foreach ($in['insert_prefixes'] as $p) {
    $prefixes[$p] = true;
}
$out = [];
foreach ($in['queries'] as $q) {
    $out[] = Dialog::isClarification($q, $prefixes);
}
echo json_encode($out, JSON_UNESCAPED_UNICODE);