<?php
declare(strict_types=1);

/**
 * Офлайн-проверка качества PHP-поиска по эталону data/site_eval.json.
 * Каталог берётся из SQLite (Storage). Порт eval_site.py.
 *   php php/tests/eval_site.php [--verbose]
 */
require __DIR__ . '/../src/Autoload.php';

use Qtool\CatalogSearch;
use Qtool\Storage;

$verbose = in_array('--verbose', $argv, true);
$repo = dirname(__DIR__, 2);
$golden = $repo . '/data/site_eval.json';
$raw = (string)file_get_contents($golden);
$raw = preg_replace('/^\xEF\xBB\xBF/', '', $raw);
$cases = json_decode($raw, true);
if (!is_array($cases)) {
    fwrite(STDERR, "Не читается эталон: $golden\n");
    exit(2);
}

$storage = new Storage();
$items = $storage->loadCatalogItems();
if (!$items) {
    fwrite(STDERR, "Пустой каталог SQLite\n");
    exit(2);
}
$engine = new CatalogSearch($items);

function numEq($a, $b): bool
{
    if (is_numeric($a) && is_numeric($b)) {
        return abs((float)$a - (float)$b) <= 1e-6;
    }
    return (string)$a === (string)$b;
}

function check(array $res, array $exp): array
{
    $errors = [];
    if (array_key_exists('family', $exp) && ($res['family'] ?? null) !== $exp['family']) {
        $errors[] = "группа: ждали {$exp['family']}, получили " . var_export($res['family'] ?? null, true);
    }
    if (array_key_exists('level', $exp) && ($res['level'] ?? null) !== $exp['level']) {
        $errors[] = "уровень: ждали {$exp['level']}, получили " . var_export($res['level'] ?? null, true);
    }
    if (isset($exp['total_min']) && (int)($res['total_found'] ?? 0) < (int)$exp['total_min']) {
        $errors[] = "найдено {$res['total_found']} < {$exp['total_min']}";
    }
    if (isset($exp['total_max']) && (int)($res['total_found'] ?? 0) > (int)$exp['total_max']) {
        $errors[] = "найдено {$res['total_found']} > {$exp['total_max']}";
    }
    foreach (['insert_code', 'holder_code', 'compatible_insert', 'fits_holder'] as $key) {
        if (array_key_exists($key, $exp) && ($res[$key] ?? null) !== $exp[$key]) {
            $errors[] = "$key: ждали {$exp[$key]}, получили " . var_export($res[$key] ?? null, true);
        }
    }
    foreach (($exp['attrs'] ?? []) as $key => $want) {
        $got = ($res['parsed'] ?? [])[$key] ?? null;
        if (!numEq($got, $want)) {
            $errors[] = "$key: ждали $want, получили " . var_export($got, true);
        }
    }
    foreach (($exp['chips_include'] ?? []) as $want) {
        $found = false;
        foreach (($res['chips'] ?? []) as $c) {
            if (str_contains(mb_strtolower((string)$c, 'UTF-8'), mb_strtolower($want, 'UTF-8'))) {
                $found = true;
                break;
            }
        }
        if (!$found) {
            $errors[] = "нет подсказки «$want»";
        }
    }
    if (!empty($exp['tap_drill'])) {
        $got = $res['tap_drill'] ?? [];
        foreach ($exp['tap_drill'] as $key => $want) {
            if (!numEq($got[$key] ?? null, $want)) {
                $errors[] = "tap_drill.$key: ждали $want, получили " . var_export($got[$key] ?? null, true);
            }
        }
    }
    if (!empty($exp['must_include'])) {
        $n = (int)($exp['top'] ?? 5);
        $top = array_slice($res['products'] ?? [], 0, $n);
        $parts = [];
        foreach ($top as $p) {
            $parts[] = ($p['sku'] ?? '') . ' ' . ($p['name'] ?? '');
        }
        $blob = mb_strtolower(implode(' ', $parts), 'UTF-8');
        if (!str_contains($blob, mb_strtolower($exp['must_include'], 'UTF-8'))) {
            $errors[] = "в первых $n нет «{$exp['must_include']}»";
        }
    }
    return $errors;
}

$passed = 0;
foreach ($cases as $case) {
    $query = $case['query'];
    $limit = max(5, (int)($case['top'] ?? 5));
    $inStock = $case['in_stock_only'] ?? true;
    $res = $engine->search($query, $limit, (bool)$inStock);
    $errors = check($res, $case);
    if ($errors) {
        echo "FAIL  $query\n";
        foreach ($errors as $err) {
            echo "      - $err\n";
        }
    } else {
        $passed++;
        if ($verbose) {
            $top = $res['products'] ?? [];
            $first = $top ? ($top[0]['sku'] ?? '') . ' | ' . mb_substr((string)($top[0]['name'] ?? ''), 0, 60, 'UTF-8') : '—';
            echo "ok    $query  [{$res['level']}, {$res['total_found']}]  $first\n";
        }
    }
}
$total = count($cases);
echo "\nИтог: $passed/$total запросов прошли (каталог: " . count($items) . " позиций)\n";
exit($passed === $total ? 0 : 1);