<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Совместимость державка↔пластина, подсверловка, общие регулярные выражения уточнений.
 * Порт блока совместимости src/catalog_search.py.
 */
final class Compat
{
    public const TAP_DRILL = [
        'M1' => 0.75, 'M1.2' => 0.95, 'M1.6' => 1.25, 'M2' => 1.6, 'M2.5' => 2.05, 'M3' => 2.5, 'M4' => 3.3,
        'M5' => 4.2, 'M6' => 5.0, 'M8' => 6.8, 'M10' => 8.5, 'M12' => 10.2, 'M14' => 12.0, 'M16' => 14.0,
        'M18' => 15.5, 'M20' => 17.5, 'M22' => 19.5, 'M24' => 21.0, 'M27' => 24.0, 'M30' => 26.5,
    ];

    public const INSERT_LETTER = ['C' => 'CNMG/CCMT', 'D' => 'DNMG/DCMT', 'V' => 'VNMG/VCMT', 'W' => 'WNMG/WCMT', 'T' => 'TNMG/TCMT', 'S' => 'SNMG/SCMT', 'R' => 'RNMG/RCMT'];

    /** R1: тип зажима державки -> допустимые типы отверстия пластины. */
    public const CLAMP_HOLE = ['C' => 'NRF', 'D' => 'AMG', 'M' => 'AMG', 'P' => 'AMG', 'S' => 'TWQU'];

    public const RE_UNDER_INSERT = '(?<![A-Za-zА-Яа-яЁё])под\s+(?:пластин[а-яё]*\s+)?([A-Za-zА-Яа-яЁё]{2,6})\s*(\d{2,6}(?:[A-Z]\d{2,4})*)?';
    public const RE_COMPAT_PHRASE = '\bпод\s+пластин[а-яё]*\b';
    public const RE_PLATE_WORD = '\bпластин[а-яё]*\b';
    public const RE_HOLDER_MENTION = '\bдержавк[а-яё]*\b';
    public const RE_PAREN_INSERT = '\(([A-Z]{2,5}\d{2,4})';
    public const RE_UNDER_SIZE = '\bпод\s+(?:мм\s+)?(?:хвост[а-яё]*|сечени[а-яё]*|диаметр[а-яё]*|хв\.?)';
    public const RE_UNDER_PLATE = '\bпод\s+пластин[а-яё]*';
    public const RE_NUMBER = '\d+(?:[.,]\d+)?(?:[xх]\d+(?:[.,]\d+)?)?';
    public const RE_THREAD_SIZE = 'm\d{1,4}(?:[.,]\d+)?';
    public const RE_TOKEN = '[a-zа-яё0-9]+(?:[.,][0-9]+)*(?:[xх][0-9]+(?:[.,][0-9]+)*)?';

    private const ADJ_TAIL = '(?:ая|яя|ое|ее|ой|ей|ою|ею|ую|юю|ые|ие|ых|их|ым|им|ыми|ими|ом|ем|ый|ий|ого|его|ому|ему)';
    private const CLARIFY_ADJ = [
        'чистов', 'получистов', 'чернов', 'наружн', 'внутренн', 'расточн', 'канавочн',
        'резьбов', 'проходн', 'подрезн', 'торцев', 'торцов', 'концев', 'дисков',
        'сферическ', 'радиусн', 'лев', 'прав', 'сменн',
    ];

    public static function clarifyWordPattern(): string
    {
        $parts = ['под', 'для', 'по', 'мм', 'обработк[а-яё]*'];
        foreach (self::CLARIFY_ADJ as $stem) {
            $parts[] = $stem . self::ADJ_TAIL;
        }
        return '(?:' . implode('|', $parts) . ')';
    }

    public static function clampAcceptsHole(?string $clamp, ?string $hole): bool
    {
        $allowed = self::CLAMP_HOLE[strtoupper($clamp ?? '')] ?? null;
        if ($allowed === null || $hole === null || $hole === '') {
            return true;
        }
        return str_contains($allowed, strtoupper($hole));
    }

    public static function tapDrillFor(?string $thread): ?array
    {
        if ($thread === null || $thread === '') {
            return null;
        }
        $m = [];
        if (preg_match('/^M(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?/u', strtoupper($thread), $m, PREG_UNMATCHED_AS_NULL) !== 1) {
            return null;
        }
        $d = (float)$m[1];
        $p = ($m[2] !== null && $m[2] !== '') ? (float)$m[2] : null;
        $key = $d == (int)$d ? 'M' . (int)$d : 'M' . $d;
        $std = self::TAP_DRILL[$key] ?? null;
        $dia = $p !== null ? round($d - $p, 2) : $std;
        if ($dia === null) {
            return null;
        }
        return ['thread' => $thread, 'drill_mm' => $dia, 'nominal_mm' => $d, 'pitch_mm' => $p];
    }

    public static function holderInsertHint(?string $code): ?string
    {
        $info = Iso5608::parseHolderCode($code);
        if (!$info || empty($info['turning']) || empty($info['insert_size'])) {
            return null;
        }
        $shape = $info['shape'];
        return (self::INSERT_LETTER[$shape] ?? $shape) . ' ' . $info['insert_size'] . 'xxxx';
    }

    public static function holderInsertCompat(?string $code): ?array
    {
        $info = Iso5608::parseHolderCode($code);
        if (!$info) {
            return null;
        }
        return [
            'shape' => $info['shape'] ?? null,
            'clearance' => $info['clearance'] ?? null,
            'size' => $info['insert_size'] ?? null,
            'shank_mm' => $info['shank_mm'] ?? null,
            'shank_diameter_mm' => $info['shank_diameter_mm'] ?? null,
            'clamp' => $info['clamp'] ?? null,
            'hand' => $info['hand'] ?? null,
            'kind' => $info['kind'] ?? null,
            'series_key' => $info['series_key'] ?? null,
            'turning' => (bool)($info['turning'] ?? false),
        ];
    }

    public static function insertCompatKey(?string $code): array
    {
        $up = strtoupper($code ?? '');
        $m = [];
        if (preg_match('/^[A-Z]+/u', $up, $m) !== 1) {
            return [];
        }
        $pref = $m[0];
        $digits = substr($up, strlen($pref));
        return [
            'prefix' => $pref,
            'shape' => $pref[0],
            'clearance' => strlen($pref) >= 2 ? $pref[1] : null,
            'hole' => strlen($pref) >= 4 ? $pref[3] : null,
            'size' => strlen($digits) >= 2 ? substr($digits, 0, 2) : null,
        ];
    }

    /** Корпуса фрез: «под APMT1604**», «(APKT1604**)» -> ['APMT1604', 'APKT1604']. */
    public static function millInsertCodes(string $name): array
    {
        $out = [];
        $mm = [];
        preg_match_all('/' . self::RE_UNDER_INSERT . '/iu', $name, $mm, PREG_UNMATCHED_AS_NULL);
        $n = count($mm[0]);
        for ($k = 0; $k < $n; $k++) {
            $g1 = $mm[1][$k];
            $raw = Normalize::low($g1);
            if (in_array($raw, ['резьбу', 'резьбы', 'пластину', 'пластины', 'пластин', 'метчика', 'метчик'], true)) {
                continue;
            }
            $word = Codes::insertPrefixFromWord($g1);
            if ($word === null) {
                continue;
            }
            $code = $word . ($mm[2][$k] ?? '');
            if (!in_array($code, $out, true)) {
                $out[] = $code;
            }
        }
        $pm = [];
        preg_match_all('/' . self::RE_PAREN_INSERT . '/u', strtoupper($name), $pm);
        foreach ($pm[1] as $code) {
            if (!Codes::isShape($code[0])) {
                continue;
            }
            if (!in_array($code, $out, true)) {
                $out[] = $code;
            }
        }
        return $out;
    }
}