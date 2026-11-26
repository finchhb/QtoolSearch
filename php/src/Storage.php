<?php
declare(strict_types=1);

namespace Qtool;

/**
 * SQLite-хранилище: каталог, словарь назначения/материала/сленга, журнал запросов,
 * закрепления «запрос -> ответ», обучающие примеры, сессии, отзывы, мета.
 * Чистый PHP (PDO SQLite), без внешних зависимостей.
 */
final class Storage
{
    public \PDO $pdo;
    public string $path;

    /** Колонки атрибутов каталога (плоские в CSV/SQLite, вкладываются в attrs при загрузке). */
    public const ATTR_COLUMNS = [
        'coating', 'material', 'size', 'diameter_mm', 'shank_mm', 'length_mm', 'cutting_length_mm',
        'teeth', 'pitch_mm', 'thread', 'angle_deg', 'radius_mm', 'width_mm', 'standard',
        'grade', 'iso_group', 'insert_code', 'insert_shape', 'clearance_angle', 'size_code', 'corner_radius_mm',
    ];

    public const CATALOG_FIELDS = [
        'id', 'sku', 'name', 'brand', 'family', 'category', 'section', 'subsection',
        'stock', 'price', 'currency', 'price_on_request', 'active', 'url',
        'coating', 'material', 'size', 'diameter_mm', 'shank_mm', 'length_mm', 'cutting_length_mm',
        'teeth', 'pitch_mm', 'thread', 'angle_deg', 'radius_mm', 'width_mm', 'standard',
        'grade', 'iso_group', 'insert_code', 'insert_shape', 'clearance_angle', 'size_code',
        'corner_radius_mm', 'extra_json',
    ];

    public function __construct(?string $path = null)
    {
        $this->path = $path ?? self::defaultPath();
        $dir = dirname($this->path);
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
        $this->pdo = new \PDO('sqlite:' . $this->path);
        $this->pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $this->pdo->setAttribute(\PDO::ATTR_DEFAULT_FETCH_MODE, \PDO::FETCH_ASSOC);
        $this->pdo->exec('PRAGMA journal_mode=WAL');
        $this->pdo->exec('PRAGMA synchronous=NORMAL');
        $this->initSchema();
    }

    public static function defaultPath(): string
    {
        $env = getenv('QTOOL_DB');
        if (is_string($env) && $env !== '') {
            return $env;
        }
        return dirname(__DIR__) . '/data/qtool.sqlite';
    }

    private function initSchema(): void
    {
        $cols = [];
        foreach (self::CATALOG_FIELDS as $f) {
            $cols[] = '"' . $f . '" TEXT';
        }
        $catalogCols = implode(",\n            ", $cols);
        $this->pdo->exec("
        CREATE TABLE IF NOT EXISTS catalog (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            $catalogCols
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_family ON catalog(family);
        CREATE INDEX IF NOT EXISTS idx_catalog_sku ON catalog(sku);

        CREATE TABLE IF NOT EXISTS dictionary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phrase TEXT NOT NULL,
            family TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            material TEXT NOT NULL DEFAULT '',
            purpose TEXT NOT NULL DEFAULT '',
            iso_group TEXT NOT NULL DEFAULT '',
            operation TEXT NOT NULL DEFAULT '',
            slang TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_dictionary_phrase ON dictionary(phrase);
        CREATE INDEX IF NOT EXISTS idx_dictionary_family ON dictionary(family);

        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            query TEXT NOT NULL DEFAULT '',
            query_norm TEXT NOT NULL DEFAULT '',
            family TEXT NOT NULL DEFAULT '',
            level TEXT NOT NULL DEFAULT '',
            total INTEGER NOT NULL DEFAULT 0,
            answer TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_query_log_norm ON query_log(query_norm);
        CREATE INDEX IF NOT EXISTS idx_query_log_ts ON query_log(ts);

        CREATE TABLE IF NOT EXISTS pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_norm TEXT NOT NULL UNIQUE,
            query TEXT NOT NULL DEFAULT '',
            skus TEXT NOT NULL DEFAULT '',
            family TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS training (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL DEFAULT '',
            query_norm TEXT NOT NULL DEFAULT '',
            skus TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            family TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_training_norm ON training(query_norm);

        CREATE TABLE IF NOT EXISTS sessions (
            sid TEXT PRIMARY KEY,
            last_query TEXT NOT NULL DEFAULT '',
            decision TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT '',
            sid TEXT NOT NULL DEFAULT '',
            rating TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            query TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        ");
    }

    // ---- мета -----------------------------------------------------------------------------------
    public function metaGet(string $key, string $default = ''): string
    {
        $st = $this->pdo->prepare('SELECT value FROM meta WHERE key=?');
        $st->execute([$key]);
        $v = $st->fetchColumn();
        return $v === false ? $default : (string)$v;
    }

    public function metaSet(string $key, string $value): void
    {
        $st = $this->pdo->prepare('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value');
        $st->execute([$key, $value]);
    }

    // ---- каталог --------------------------------------------------------------------------------
    public function catalogCount(): int
    {
        return (int)$this->pdo->query('SELECT COUNT(*) FROM catalog')->fetchColumn();
    }

    /** Загрузка каталога в структуру items, идентичную Python load_site_catalog(). */
    public function loadCatalogItems(): array
    {
        $items = [];
        $st = $this->pdo->query('SELECT * FROM catalog');
        while ($row = $st->fetch()) {
            $attrs = [];
            foreach (self::ATTR_COLUMNS as $key) {
                $val = trim((string)($row[$key] ?? ''));
                if ($val === '') {
                    continue;
                }
                if ($key === 'teeth' || $key === 'hrc') {
                    $num = self::f($val);
                    if ($num !== null) {
                        $attrs[$key] = (int)$num;
                    }
                } elseif (str_ends_with($key, '_mm') || str_ends_with($key, '_deg')) {
                    $num = self::f($val);
                    if ($num !== null) {
                        $attrs[$key] = $num;
                    }
                } else {
                    $attrs[$key] = $val;
                }
            }
            $extraRaw = (string)($row['extra_json'] ?? '');
            if ($extraRaw !== '') {
                $extra = json_decode($extraRaw, true);
                if (is_array($extra)) {
                    $attrs = array_merge($attrs, $extra);
                }
            }
            $items[] = [
                'id' => (string)($row['id'] ?? ''),
                'sku' => (string)($row['sku'] ?? ''),
                'name' => (string)($row['name'] ?? ''),
                'brand' => (string)($row['brand'] ?? ''),
                'family' => (string)($row['family'] ?? ''),
                'category' => (string)($row['category'] ?? ''),
                'section' => (string)($row['section'] ?? ''),
                'subsection' => (string)($row['subsection'] ?? ''),
                'stock' => self::i($row['stock'] ?? null) ?? 0,
                'price' => self::f($row['price'] ?? null) ?? 0.0,
                'currency' => (string)($row['currency'] ?? '') ?: 'RUB',
                'price_on_request' => ((string)($row['price_on_request'] ?? '0')) === '1',
                'active' => ((string)($row['active'] ?? '1')) !== '0',
                'url' => (string)($row['url'] ?? ''),
                'attrs' => $attrs,
            ];
        }
        return $items;
    }

    /** Полная замена каталога (атомарно, в транзакции). */
    public function replaceCatalog(array $rows): int
    {
        $this->pdo->beginTransaction();
        try {
            $this->pdo->exec('DELETE FROM catalog');
            $fields = self::CATALOG_FIELDS;
            $ph = implode(',', array_fill(0, count($fields), '?'));
            $colList = implode(',', array_map(static fn($f) => '"' . $f . '"', $fields));
            $st = $this->pdo->prepare("INSERT INTO catalog($colList) VALUES($ph)");
            $n = 0;
            foreach ($rows as $row) {
                $vals = [];
                foreach ($fields as $f) {
                    $v = $row[$f] ?? '';
                    $vals[] = is_bool($v) ? ($v ? '1' : '0') : (string)$v;
                }
                $st->execute($vals);
                $n++;
            }
            $this->pdo->commit();
            return $n;
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
    }

    // ---- числовые помощники (порт _f/_i) --------------------------------------------------------
    public static function f($s): ?float
    {
        if ($s === null) {
            return null;
        }
        $txt = trim(str_replace(',', '.', (string)$s));
        if ($txt === '' || in_array(strtolower($txt), ['nan', 'none'], true)) {
            return null;
        }
        if (!is_numeric($txt)) {
            return null;
        }
        return (float)$txt;
    }

    public static function i($s): ?int
    {
        $v = self::f($s);
        return $v === null ? null : (int)round($v);
    }
}