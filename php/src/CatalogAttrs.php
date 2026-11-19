<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Общие атрибуты из названия: покрытие, стандарт, HRC, марка, материал, резьба, зубья,
 * размеры. Порт функций src/site_catalog.py, используемых парсером и приёмом каталога.
 */
final class CatalogAttrs
{
    public const NUM = '\d+(?:[.,]\d+)?';
    public const RE_DIA = '(?:Ø|⌀|D\s*=|d\s*=|диаметр\s*)\s*(' . self::NUM . ')';
    public const RE_MM = '(?<![\w.])(' . self::NUM . ')\s*мм\b';
    private const RE_TRIPLE = '(?<![\w.])(' . self::NUM . ')\s*[xх×*]\s*(' . self::NUM . ')(?:\s*[xх×*]\s*(' . self::NUM . '))?(?:\s*[xх×*]\s*(' . self::NUM . '))?';
    private const RE_METRIC = '(?<![A-Za-zА-Яа-я0-9])[MmМм]\s*(\d+(?:[.,]\d+)?)\s*(?:[xXхХ×*]\s*(\d+(?:[.,]\d+)?))?';
    private const RE_INCH = '(?<![\w.])(\d+\/\d+)\s*-\s*(\d+)\s*(UNC|UNF|UNEF|NPT|BSP)?';
    private const RE_PIPE = '(?<![A-Za-z0-9])G\s*(\d+(?:[.\/]\d+)?)\b';
    private const RE_ANGLE = '(' . self::NUM . ')\s*°';
    private const RE_STANDARD = '(ГОСТ\s*[\d.\-]+|DIN\s*\d+|ISO\s*\d+|ANSI\s*[\w.\-]+)';
    private const RE_COATING = '\b(TiSiN|TiAlN|AlTiN|AlCrN|TiCN|TiN|DLC|nACo|nano|ZrN|Black|FIRE|PVD|CVD)\b';
    private const RE_HRC = 'HRC\s*(\d+)';
    private const GRADE_HINT = '^(LF\d{4}|LDA|MHN\d+[A-Z]?|PC\d{4}|DP\d+|H\d{2}|K\d{2}|P\d{2}|M\d{2}[A-Z]?|[A-Z]{2}\d{3,4})$';

    /** @return list<float> */
    public static function dims(string $name): array
    {
        $mm = [];
        preg_match_all('/' . self::RE_TRIPLE . '/u', $name, $mm, PREG_UNMATCHED_AS_NULL);
        // preg_match_all groups: $mm[1..4] arrays per match
        $n = count($mm[0]);
        for ($k = 0; $k < $n; $k++) {
            $vals = [];
            for ($g = 1; $g <= 4; $g++) {
                $v = $mm[$g][$k] ?? null;
                if ($v !== null && $v !== '') {
                    $vals[] = (float)str_replace(',', '.', $v);
                }
            }
            if (count($vals) >= 2) {
                return $vals;
            }
        }
        return [];
    }

    public static function extractCommon(string $name): array
    {
        $out = [];
        $m = [];
        if (preg_match('/' . self::RE_COATING . '/iu', $name, $m)) {
            $out['coating'] = $m[1];
        }
        if (preg_match('/' . self::RE_STANDARD . '/iu', $name, $m)) {
            $out['standard'] = mb_strtoupper(preg_replace('/\s+/u', ' ', $m[1]), 'UTF-8');
        }
        if (preg_match('/' . self::RE_HRC . '/iu', $name, $m)) {
            $out['hrc'] = (int)$m[1];
        }
        $grade = null;
        $toks = [];
        preg_match_all('/[A-Za-zА-Яа-я0-9-]+/u', $name, $toks);
        foreach ($toks[0] as $tok) {
            $up = str_replace('К', 'K', mb_strtoupper($tok, 'UTF-8'));
            $hasDigit = preg_match('/\d/', $up) === 1;
            if ($hasDigit && preg_match('/' . self::GRADE_HINT . '/iu', $up) && !Normalize::fullmatch('\d+', $up)) {
                $starts = false;
                foreach (['LF', 'LDA', 'MHN', 'PC', 'DP', 'H', 'K', 'P', 'M'] as $pfx) {
                    if (str_starts_with($up, $pfx)) {
                        $starts = true;
                        break;
                    }
                }
                if ($starts || $up === 'VHM') {
                    $grade = $up;
                    break;
                }
            }
        }
        if ($grade !== null) {
            $out['grade'] = $grade;
        }
        $low = Normalize::lower($name);
        if (str_contains($low, 'твердосплав') || str_contains($low, 'vhm')) {
            $out['material'] = 'твердый сплав';
        } elseif (str_contains($low, 'hss-co') || str_contains($low, 'р6м5к5') || str_contains($low, 'p6m5k5')) {
            $out['material'] = 'HSS-Co';
        } elseif (str_contains($low, 'hss-e')) {
            $out['material'] = 'HSS-E';
        } elseif (str_contains($low, 'hss') || str_contains($low, 'р6м5') || str_contains($low, 'p6m5')) {
            $out['material'] = 'HSS';
        } elseif (str_contains($low, '9хс')) {
            $out['material'] = '9ХС';
        }
        return $out;
    }

    public static function extractThread(string $name): array
    {
        $up = str_replace(['М', 'Х', '*'], ['M', 'X', 'X'], mb_strtoupper($name, 'UTF-8'));
        $out = [];
        // B10: не ловить резьбу внутри кода пластины (G — зажим/чистка, не труба)
        $normalized = Normalize::cyrillicCodeLetters($up);
        if (preg_match('/^[A-Z]{2,5}\d{4,6}[A-Z]{0,4}$/u', $normalized)) {
            return [];
        }
        $m = [];
        if (preg_match('/' . self::RE_PIPE . '/u', $up, $m)) {
            $out['thread'] = 'G' . $m[1];
            $out['thread_type'] = 'pipe';
            return $out;
        }
        if (preg_match('/' . self::RE_INCH . '/iu', $up, $m, PREG_UNMATCHED_AS_NULL) && str_contains($m[1], '/')) {
            $kind = mb_strtoupper($m[3] ?? 'UNC', 'UTF-8');
            $out['thread'] = $m[1] . '-' . $m[2] . $kind;
            $out['thread_type'] = 'inch';
            $out['diameter_inch'] = $m[1];
            return $out;
        }
        if (preg_match('/' . self::RE_METRIC . '/u', $up, $m, PREG_UNMATCHED_AS_NULL)) {
            $dNum = self::fmtNumStr($m[1]);
            $out['thread'] = ($m[2] !== null && $m[2] !== '') ? 'M' . $dNum . 'x' . self::fmtNumStr($m[2]) : 'M' . $dNum;
            $out['thread_type'] = 'metric';
            $out['diameter_mm'] = (float)str_replace(',', '.', $m[1]);
            if ($m[2] !== null && $m[2] !== '') {
                $out['pitch_mm'] = (float)str_replace(',', '.', $m[2]);
            }
            $low = Normalize::lower($name);
            if (str_contains($low, 'раскат')) {
                $out['tap_kind'] = 'forming';
            } elseif (str_contains($low, 'гаечн')) {
                $out['tap_kind'] = 'nut';
            } elseif (str_contains($low, 'трубн')) {
                $out['tap_kind'] = 'pipe';
            } elseif (str_contains($low, 'коническ')) {
                $out['tap_kind'] = 'taper';
            } elseif (str_contains($low, 'сквозн') || str_contains($low, 'м/р')) {
                $out['tap_kind'] = 'through';
            }
        }
        return $out;
    }

    /** Python _fmt_num: целое -> без точки, иначе %g. */
    public static function fmtNumStr(string $s): string
    {
        $v = (float)str_replace(',', '.', $s);
        if ($v == (int)$v) {
            return (string)(int)$v;
        }
        return Normalize::gFormat($v);
    }

    public static function extractTeeth(string $name): ?int
    {
        $patterns = ['(?<![\w.])(\d+)\s*F\b', '[Zz]\s*=\s*(\d+)', '(' . self::NUM . ')\s*зуб'];
        foreach ($patterns as $rx) {
            $m = [];
            if (preg_match('/' . $rx . '/u', $name, $m)) {
                $v = Storage::i($m[1]);
                if ($v !== null && $v > 0 && $v <= 100) {
                    return $v;
                }
            }
        }
        return null;
    }

    /** Конус и размеры патрона/оправки: «BT50-SLN25-100» -> taper, d, l. */
    public static function accessoryMount(string $name): array
    {
        $up = mb_strtoupper($name, 'UTF-8');
        $m = [];
        if (preg_match('/(?<![A-Z0-9])(HSK|BT|SK|NT|DIN)[\s-]?(\d{2})(?!\d)/u', $up, $m, PREG_OFFSET_CAPTURE) !== 1) {
            return [];
        }
        $out = ['taper' => $m[1][0] . $m[2][0]];
        $endChar = mb_strlen(substr($up, 0, $m[0][1]), 'UTF-8') + mb_strlen($m[0][0], 'UTF-8');
        $tail = mb_substr($up, $endChar, 16, 'UTF-8');
        $nums = [];
        preg_match_all('/\d{2,3}/u', $tail, $nums);
        if (count($nums[0]) >= 2) {
            $out['d'] = (int)$nums[0][0];
            $out['l'] = (int)$nums[0][1];
        }
        return $out;
    }

    public static function slotMmFromName(string $name): ?int
    {
        $m = [];
        if (preg_match('/паз\.?\s*(\d{1,2})(?!\d)/iu', $name, $m)) {
            return (int)$m[1];
        }
        return null;
    }

    public static function gaugeDiameter(string $name): ?float
    {
        $m = [];
        if (preg_match('/гладк\w*\s*(\d+(?:[.,]\d+)?)/iu', $name, $m)) {
            return (float)str_replace(',', '.', $m[1]);
        }
        return null;
    }

    public static function chuckCapacity(string $name): ?int
    {
        $m = [];
        if (preg_match('/(?<![A-ZА-Я0-9])[A-ZА-Я]{2,5}-(\d{1,2})(?!\d)/u', mb_strtoupper($name, 'UTF-8'), $m)) {
            return (int)$m[1];
        }
        return null;
    }
}