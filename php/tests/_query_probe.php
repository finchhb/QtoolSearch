<?php
require __DIR__ . '/../src/Autoload.php';

use Qtool\Query;

$in = json_decode(stream_get_contents(STDIN), true);
$prefixes = [];
foreach ($in['insert_prefixes'] as $p) {
    $prefixes[$p] = true;
}
$out = [];
foreach ($in['queries'] as $q) {
    $query = new Query($q, $prefixes);
    $out[] = $query->toArray();
}
echo json_encode($out, JSON_UNESCAPED_UNICODE);