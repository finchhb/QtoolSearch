<?php
require __DIR__ . '/../src/Autoload.php';

use Qtool\CatalogSearch;

$items = json_decode((string)file_get_contents(__DIR__ . '/_items.json'), true);
$engine = new CatalogSearch($items);
$queries = json_decode(stream_get_contents(STDIN), true);
$out = [];
foreach ($queries as $q) {
    $out[] = $engine->search($q);
}
echo json_encode($out, JSON_UNESCAPED_UNICODE);