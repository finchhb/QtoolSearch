<?php
declare(strict_types=1);

/**
 * Импорт снимка каталога catalog_site.csv в SQLite.
 * Запуск: php bin/import_catalog.php [путь_к_csv]
 */
require __DIR__ . '/../src/Autoload.php';

use Qtool\Storage;

$csv = $argv[1] ?? dirname(__DIR__, 2) . '/data/catalog_site.csv';
if (!is_file($csv)) {
    fwrite(STDERR, "CSV не найден: $csv\n");
    exit(1);
}

$store = new Storage();
$fh = fopen($csv, 'rb');
if ($fh === false) {
    fwrite(STDERR, "Не открыть $csv\n");
    exit(1);
}
// снять BOM
$bom = fread($fh, 3);
if ($bom !== "\xEF\xBB\xBF") {
    rewind($fh);
}
$header = fgetcsv($fh, 0, ',', '"', '\\');
if ($header === false) {
    fwrite(STDERR, "Пустой CSV\n");
    exit(1);
}
$header = array_map(static fn($h) => trim((string)$h), $header);
$fields = Storage::CATALOG_FIELDS;

$rows = [];
while (($data = fgetcsv($fh, 0, ',', '"', '\\')) !== false) {
    if ($data === [null]) {
        continue;
    }
    $row = [];
    foreach ($header as $i => $col) {
        $row[$col] = $data[$i] ?? '';
    }
    $rows[] = $row;
}
fclose($fh);

$n = $store->replaceCatalog($rows);
$store->metaSet('catalog_source', $csv);
$store->metaSet('catalog_count', (string)$n);
$store->metaSet('catalog_imported_at', date('c'));
echo "Импортировано позиций: $n\n";
echo "БД: {$store->path}\n";