<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Детерминированный разбор обозначений сменных пластин ISO 1832 (ГОСТ 19042-80).
 * Порт src/iso1832.py. Только таблицы и регулярные выражения, без LLM.
 */
final class Iso1832
{
    public const RUS_SHAPES = [
        'ромб' => 'C', 'треугольник' => 'T', 'квадрат' => 'S', 'круг' => 'R', 'круглая' => 'R',
        'тригон' => 'W', 'ломаный треугольник' => 'W', 'шестигранник' => 'H',
        'восьмигранник' => 'O', 'пятигранник' => 'P', 'параллелограмм' => 'A',
    ];

    /** shape => [angle|null, title] */
    public const SHAPES = [
        'A' => [85, 'параллелограмм 85°'], 'B' => [82, 'параллелограмм 82°'],
        'C' => [80, 'ромб 80°'], 'D' => [55, 'ромб 55°'], 'E' => [75, 'ромб 75°'],
        'M' => [86, 'ромб 86°'], 'V' => [35, 'ромб 35°'], 'K' => [55, 'параллелограмм 55°'],
        'F' => [84, 'параллелограмм 84°'], 'H' => [120, 'шестигранник'], 'O' => [135, 'восьмигранник'],
        'P' => [108, 'пятигранник'], 'R' => [null, 'круглая'], 'S' => [90, 'квадрат'],
        'T' => [60, 'треугольник'], 'W' => [80, 'тригон 80°'], 'L' => [90, 'прямоугольная'],
    ];

    private const D = [3.97, 4.76, 5.56, 6.35, 7.94, 9.525, 12.7, 15.875, 19.05, 25.4, 31.75];
    private const ROWS = [
        'S' => ['03', '04', '05', '06', '07', '09', '12', '15', '19', '25', '31'],
        'T' => ['06', '08', '09', '11', '13', '16', '22', '27', '33', '44', '54'],
        'C' => ['04', '04', '05', '06', '08', '09', '12', '16', '19', '25', '32'],
        'D' => [null, '05', '06', '07', '09', '11', '15', '19', '23', '31', '38'],
        'E' => [null, '04', '05', '06', '08', '09', '13', '16', '19', '26', '32'],
        'M' => [null, '04', '05', '06', '07', '09', '12', '15', '19', '25', '31'],
        'V' => [null, '08', '09', '11', '13', '16', '22', '27', '33', '44', '54'],
        'W' => [null, null, '03', '04', '05', '06', '08', '10', '13', '17', '21'],
        'R' => [null, null, null, '06', '07', '09', '12', '15', '19', '25', '31'],
        'H' => [null, null, null, '03', '04', '05', '07', '09', '11', '14', '18'],
        'O' => [null, null, null, '02', '03', '04', '05', '06', '07', '10', '13'],
        'P' => [null, null, null, '04', '05', '07', '09', '11', '13', '18', '23'],
    ];

    public const R_METRIC = ['06' => 6.0, '08' => 8.0, '10' => 10.0, '12' => 12.0, '16' => 16.0, '20' => 20.0, '25' => 25.0, '32' => 32.0];
    public const THICK = ['01' => 1.59, 'T1' => 1.98, '02' => 2.38, '03' => 3.18, 'T3' => 3.97, '04' => 4.76,
        '05' => 5.56, '06' => 6.35, '07' => 7.94, '08' => 8.0, '09' => 9.52, '12' => 12.7];
    public const RELIEF = ['A' => 3, 'B' => 5, 'C' => 7, 'D' => 15, 'E' => 20, 'F' => 25, 'G' => 30, 'N' => 0, 'P' => 11];

    private const RU_SHAPE = [
        ['ломаный треугольн', ['W']], ['тригон', ['W']],
        ['ромб', ['C', 'D', 'V', 'E', 'M']],
        ['треугольн', ['T']], ['трехгран', ['T']], ['треух', ['T']],
        ['квадрат', ['S']], ['четырехгран', ['S']],
        ['кругл', ['R']], ['шестигран', ['H', 'W']], ['восьмигран', ['O']],
        ['пятигран', ['P']], ['прямоугольн', ['L']], ['параллелограмм', ['A', 'B', 'K', 'F']],
    ];

    private const ISO_RE = '\b([ABCDEFGHKLMOPRSTVW])([ABCDEGFNP])([ACEFGHJKLMNU])([NRFAMGWTQUBHCJX])[-\s]?(\d{2})(T\d|\d{2})(\d{2}|M0|MO)([RL])?(?![0-9A-Z])';
    private const PARTIAL_RE = '\b([ABCDEFGHKLMOPRSTVW])([ABCDEGFNP])([ACEFGHJKLMNU])([NRFAMGWTQUBHCJX])[-\s]?(\d{1,5}(?:T\d)?)?(?![0-9A-Z])';
    private const ANGLE_RE = '(?<![\d.,])(108|120|135|35|55|75|80|86|85|82|84|90|45|60)\s*(?:°|град)';

    /** @var array<string,array<string,list<float>>> shape => code => [d...] */
    private static array $size2d = [];
    /** @var array<string,true> */
    private static array $allSizeCodes = [];
    /** @var array<int,string> */
    private static array $reliefByDeg = [];
    private static bool $init = false;

    private static function init(): void
    {
        if (self::$init) {
            return;
        }
        foreach (self::ROWS as $sh => $codes) {
            foreach (self::D as $i => $d) {
                $c = $codes[$i];
                if ($c !== null && $c !== '') {
                    self::$size2d[$sh][$c][] = $d;
                    self::$allSizeCodes[$c] = true;
                }
            }
        }
        foreach (self::RELIEF as $k => $v) {
            self::$reliefByDeg[$v] = $k;
        }
        self::$init = true;
    }

    private static function size2d(string $shape, string $code): array
    {
        self::init();
        return self::$size2d[$shape][$code] ?? [];
    }

    /** Омоглифы ISO 1832 + upper + O перед цифрой -> 0. */
    public static function normCode(string $text): string
    {
        $map = [
            'А' => 'A', 'В' => 'B', 'С' => 'C', 'Е' => 'E', 'Н' => 'H', 'К' => 'K', 'М' => 'M', 'О' => 'O', 'Р' => 'P', 'Т' => 'T', 'Х' => 'X', 'У' => 'Y',
            'а' => 'A', 'в' => 'B', 'с' => 'C', 'е' => 'E', 'н' => 'H', 'к' => 'K', 'м' => 'M', 'о' => 'O', 'р' => 'P', 'т' => 'T', 'х' => 'X', 'у' => 'Y',
        ];
        $s = '';
        foreach (mb_str_split($text, 1, 'UTF-8') as $ch) {
            $s .= $map[$ch] ?? $ch;
        }
        $s = mb_strtoupper($s, 'UTF-8');
        return preg_replace('/O(?=\d)/u', '0', $s);
    }

    public static function edgeLen(string $shape, float $d): ?float
    {
        $a = self::SHAPES[$shape][0];
        if (in_array($shape, ['C', 'D', 'E', 'M', 'V', 'A', 'B', 'K', 'F'], true)) {
            return $d / sin(deg2rad((float)$a));
        }
        $n = ['T' => 3, 'S' => 4, 'P' => 5, 'H' => 6, 'O' => 8][$shape] ?? null;
        return $n !== null ? $d * tan(M_PI / $n) : null;
    }

    /** @return array{0:list<float>,1:list<string>} */
    public static function resolveSize(string $shape, string $code, ?string $corner = null): array
    {
        self::init();
        $warn = [];
        if ($shape === 'R') {
            if ($corner === 'M0' || $corner === 'MO') {
                return [isset(self::R_METRIC[$code]) ? [self::R_METRIC[$code]] : [], $warn];
            }
            if ($corner === '00') {
                return [self::size2d('R', $code), $warn];
            }
            $merged = array_merge(self::size2d('R', $code), isset(self::R_METRIC[$code]) ? [self::R_METRIC[$code]] : []);
            $cand = array_values(array_unique($merged));
            if (count($cand) > 1) {
                $warn[] = "Круглая $code: метрический/дюймовый ряд не различить без M0/00";
            }
            return [$cand, $warn];
        }
        $cand = self::size2d($shape, $code);
        if (count($cand) > 1) {
            $warn[] = "$shape$code: стандарт допускает d=" . self::pyList($cand) . ' — уточните';
        }
        return [$cand, $warn];
    }

    /** Python repr списка чисел для строк предупреждений: [9.525, 12.7]. */
    private static function pyList(array $vals): string
    {
        $parts = [];
        foreach ($vals as $v) {
            $parts[] = self::pyFloat($v);
        }
        return '[' . implode(', ', $parts) . ']';
    }

    private static function pyFloat(float $v): string
    {
        $s = (string)$v;
        // PHP (string)9.525 = "9.525"; (string)12.7 = "12.7"; целые float -> "6" как Python "6.0"
        if (!str_contains($s, '.') && !str_contains($s, 'E')) {
            $s .= '.0';
        }
        return $s;
    }

    public static function parseCode(string $token): ?array
    {
        $m = [];
        if (preg_match('/' . self::ISO_RE . '/u', self::normCode($token), $m, PREG_UNMATCHED_AS_NULL) !== 1) {
            return null;
        }
        [$full, $sh, $rel, $tol, $typ, $size, $th, $corner, $hand] = $m;
        [$d, $warn] = self::resolveSize($sh, $size, $corner);
        if ($corner === 'M0' || $corner === 'MO') {
            $r = null;
        } elseif ($corner === '00') {
            $r = 0.0;
        } else {
            $r = (int)$corner / 10.0;
        }
        return [
            'code' => str_replace([' ', '-'], '', $full), 'shape' => $sh, 'relief' => $rel,
            'tolerance' => $tol, 'type' => $typ, 'size_code' => $size, 'thickness_code' => $th,
            'thickness' => self::THICK[$th] ?? null, 'corner_code' => $corner, 'corner_r' => $r, 'hand' => $hand ?? '',
            'ic_d' => count($d) === 1 ? $d[0] : null, 'ic_candidates' => $d, 'warnings' => $warn,
        ];
    }

    /** find_codes: список разобранных кодов с char-span. */
    public static function findCodes(string $text): array
    {
        $norm = self::normCode($text);
        $out = [];
        $mm = [];
        preg_match_all('/' . self::ISO_RE . '/u', $norm, $mm, PREG_OFFSET_CAPTURE);
        foreach ($mm[0] as $hit) {
            [$full, $byteOff] = $hit;
            $p = self::parseCode($full);
            if ($p) {
                $start = mb_strlen(substr($norm, 0, $byteOff), 'UTF-8');
                $p['span'] = [$start, $start + mb_strlen($full, 'UTF-8')];
                $out[] = $p;
            }
        }
        return $out;
    }

    /** @return array{0:string,1:list<string>,2:int|null} */
    public static function detectShape(string $text): array
    {
        $codes = self::findCodes($text);
        if ($codes) {
            $s = $codes[0]['shape'];
            return [$s, [$s], self::SHAPES[$s][0]];
        }
        $t = Normalize::low($text);
        if (str_contains($t, 'ломан') && str_contains($t, 'треугольн')) {
            return ['W', ['W'], 80];
        }
        $cands = [];
        foreach (self::RU_SHAPE as [$stem, $letters]) {
            if (str_contains($t, $stem)) {
                foreach ($letters as $L) {
                    if (!in_array($L, $cands, true)) {
                        $cands[] = $L;
                    }
                }
            }
        }
        $ang = null;
        $m = [];
        if (preg_match('/' . self::ANGLE_RE . '/u', $t, $m)) {
            $ang = (int)$m[1];
        } elseif (preg_match('/(?:ромб\w*|параллелограмм\w*)\s+(\d{2})(?!\d)/u', $t, $m2)) {
            $ang = (int)$m2[1];
        }
        if ($ang !== null) {
            $narrowed = array_values(array_filter($cands, static fn($L) => self::SHAPES[$L][0] === $ang));
            if ($narrowed) {
                $cands = $narrowed;
            } elseif (!$cands) {
                foreach (self::SHAPES as $L => [$a, $_]) {
                    if ($a === $ang) {
                        $cands[] = $L;
                    }
                }
            }
        }
        if (count($cands) === 1) {
            return [$cands[0], $cands, $ang];
        }
        return ['', $cands, $ang];
    }

    public static function detectClearance(string $text): string
    {
        self::init();
        $codes = self::findCodes($text);
        if ($codes) {
            return $codes[0]['relief'];
        }
        $t = Normalize::lower($text);
        $m = [];
        if (preg_match('/задн\w*\s+угол\s*[:=]?\s*(\d{1,2})(?!\d)/u', $t, $m) && isset(self::$reliefByDeg[(int)$m[1]])) {
            return self::$reliefByDeg[(int)$m[1]];
        }
        if (preg_match('/(?<![\d.,])(0|3|5|7|11|15|20|25|30)\s*(?:°|град)/u', $t, $m)) {
            return self::$reliefByDeg[(int)$m[1]] ?? '';
        }
        foreach (['негативн', 'двухсторонн', 'двусторонн', 'без заднего угла'] as $w) {
            if (str_contains($t, $w)) {
                return 'N';
            }
        }
        foreach (['позитивн', 'односторонн'] as $w) {
            if (str_contains($t, $w)) {
                return 'C';
            }
        }
        return '';
    }

    public static function detectRadius(string $text): ?float
    {
        $codes = self::findCodes($text);
        if ($codes) {
            return $codes[0]['corner_r'];
        }
        $t = str_replace(',', '.', Normalize::lower($text));
        $m = [];
        if (preg_match('/(?<![a-zа-я0-9])(?:r|радиус\w*)\s*[:=]?\s*(\d+(?:\.\d+)?)(?![\d])/u', $t, $m)) {
            $v = (float)$m[1];
            if ($v <= 3.2) {
                return $v;
            }
        }
        if (preg_match('/(?<![a-zа-я0-9])r0(\d)(?![\d])/u', $t, $m)) {
            return (int)$m[1] / 10.0;
        }
        return null;
    }

    private static function icToCode(string $shape, float $ic): ?string
    {
        self::init();
        foreach (self::$size2d as $s => $codes) {
            if ($s !== $shape) {
                continue;
            }
            foreach ($codes as $c => $ds) {
                foreach ($ds as $d) {
                    if (abs($d - $ic) < 0.01) {
                        return $c;
                    }
                }
            }
        }
        if ($shape === 'R') {
            foreach (self::R_METRIC as $c => $d) {
                if (abs($d - $ic) < 0.01) {
                    return $c;
                }
            }
        }
        return null;
    }

    public static function detectSize(string $text, string $shape = ''): array
    {
        self::init();
        $t = str_replace(',', '.', Normalize::lower($text));
        $up = self::normCode($text);
        $out = ['size_code' => '', 'ic_d' => null, 'warnings' => []];
        $ang = self::detectShape($text)[2];
        $m = [];
        if (preg_match('/(?<![0-9A-Z])(\d{2})(T\d|\d{2})(\d{2})(?![0-9])/u', $up, $m)
            && isset(self::THICK[$m[2]]) && isset(self::$allSizeCodes[$m[1]])) {
            if ($shape === '' || isset(self::$size2d[$shape][$m[1]]) || $shape === 'R') {
                $out['size_code'] = $m[1];
                [$d, $w] = $shape !== '' ? self::resolveSize($shape, $m[1]) : [[], []];
                if (count($d) === 1) {
                    $out['ic_d'] = $d[0];
                }
                $out['warnings'] = array_merge($out['warnings'], $w);
                return $out;
            }
        }
        if (preg_match('/(?<![0-9A-Z])(\d{2})(T\d|\d{2})(?![0-9])/u', $up, $m)
            && isset(self::THICK[$m[2]]) && isset(self::$allSizeCodes[$m[1]])) {
            if ($shape === '' || isset(self::$size2d[$shape][$m[1]]) || $shape === 'R') {
                $out['size_code'] = $m[1];
                [$d, $w] = $shape !== '' ? self::resolveSize($shape, $m[1]) : [[], []];
                if (count($d) === 1) {
                    $out['ic_d'] = $d[0];
                }
                $out['warnings'] = array_merge($out['warnings'], $w);
                return $out;
            }
        }
        if (preg_match('/(?:\bd\s*[:=]?\s*|\bic\s*[:=]?\s*|вписанн\w*\s*|ø\s*|диаметр\w*\s*)(\d{1,2}(?:\.\d+)?)/u', $t, $m)) {
            $ic = (float)$m[1];
            $out['ic_d'] = $ic;
            if ($shape !== '') {
                $c = self::icToCode($shape, $ic);
                if ($c !== null) {
                    $out['size_code'] = $c;
                }
            }
            return $out;
        }
        $m = [];
        if (preg_match('/(?:размер\w*|габарит\w*|кромк\w*)\s*[:=-]?\s*(\d{1,2})(?!\d)/u', $t, $m)
            || preg_match('/(?<![\d.,])(\d{1,2})\s*(?:размер|габарит)/u', $t, $m)) {
            $code = sprintf('%02d', (int)$m[1]);
            $out['size_code'] = $code;
            if ($shape !== '') {
                [$d, $w] = self::resolveSize($shape, $code);
                if (count($d) === 1) {
                    $out['ic_d'] = $d[0];
                }
                $out['warnings'] = array_merge($out['warnings'], $w);
            }
            return $out;
        }
        if (preg_match('/(?:ромб\w*|треугольн\w*|треух\w*|квадрат\w*|тригон\w*|шестигран\w*|кругл\w*|пятигран\w*|восьмигран\w*)\s+(?:№\s*)?(\d{1,2})(?!\d)/u', $t, $m)) {
            $n = (int)$m[1];
            $code = sprintf('%02d', $n);
            if ($shape !== '' && $n !== $ang && (isset(self::$size2d[$shape][$code]) || ($shape === 'R' && isset(self::R_METRIC[$code])))) {
                $out['size_code'] = $code;
                [$d, $w] = self::resolveSize($shape, $code);
                if (count($d) === 1) {
                    $out['ic_d'] = $d[0];
                }
                $out['warnings'] = array_merge($out['warnings'], $w);
                return $out;
            }
        }
        if (preg_match('/(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*мм\b/u', $t, $m)) {
            $v = (float)$m[1];
            if ($v != (int)$v) {
                $out['ic_d'] = $v;
                if ($shape !== '') {
                    $c = self::icToCode($shape, $v);
                    if ($c !== null) {
                        $out['size_code'] = $c;
                    }
                } else {
                    $out['warnings'][] = 'Дробный размер в мм принят за диаметр вписанной окружности; укажите форму/угол';
                }
                return $out;
            }
            if ($shape !== '' && $shape !== 'R') {
                foreach (self::$size2d[$shape] ?? [] as $c => $ds) {
                    foreach ($ds as $d) {
                        $el = self::edgeLen($shape, $d);
                        if ($el !== null && (int)$el === (int)$v) {
                            $out['size_code'] = $c;
                            $out['ic_d'] = $d;
                            $out['warnings'][] = (int)$v . ' мм — длина кромки по ГОСТ 19042-80 (d=' . self::pyFloat($d) . ' мм)';
                            return $out;
                        }
                    }
                }
            } elseif ($shape === 'R') {
                $c = sprintf('%02d', (int)$v);
                if (isset(self::R_METRIC[$c])) {
                    $out['size_code'] = $c;
                    $out['ic_d'] = self::R_METRIC[$c];
                    return $out;
                }
            }
        }
        return $out;
    }

    /** split_positions: разбивка мульти-запроса на позиции с количеством. */
    public static function splitPositions(string $text): array
    {
        $out = [];
        $chunks = preg_split('/[\n;|]+/u', $text);
        foreach ($chunks as $raw) {
            $chunk = trim(preg_replace('/^\s*\d+[.)]\s*/u', '', $raw));
            if ($chunk === '') {
                continue;
            }
            $norm = self::normCode($chunk);
            $mm = [];
            preg_match_all('/' . self::ISO_RE . '/u', $norm, $mm, PREG_OFFSET_CAPTURE);
            $codes = $mm[0];
            $segs = [];
            $charLen = mb_strlen($chunk, 'UTF-8');
            if (count($codes) > 1) {
                foreach ($codes as $i => $hit) {
                    $startByte = $hit[1];
                    $start = mb_strlen(substr($norm, 0, $startByte), 'UTF-8');
                    $end = isset($codes[$i + 1])
                        ? mb_strlen(substr($norm, 0, $codes[$i + 1][1]), 'UTF-8')
                        : $charLen;
                    $segs[] = mb_substr($chunk, $start, $end - $start, 'UTF-8');
                }
            } else {
                $segs = [$chunk];
            }
            foreach ($segs as $seg) {
                $q = [];
                $hasQty = preg_match('/(?:(\d+)\s*(?:шт\.?|штук|уп\.?|pcs?)\b|[xх*]\s*(\d+)\s*$)/iu', $seg, $q, PREG_OFFSET_CAPTURE | PREG_UNMATCHED_AS_NULL);
                if ($hasQty) {
                    $qty = null;
                    foreach ([$q[1], $q[2]] as $g) {
                        if ($g[0] !== null && $g[0] !== '') {
                            $qty = (int)$g[0];
                            break;
                        }
                    }
                    $qStart = mb_strlen(substr($seg, 0, $q[0][1]), 'UTF-8');
                    $qEnd = $qStart + mb_strlen($q[0][0], 'UTF-8');
                    $clean = trim(mb_substr($seg, 0, $qStart, 'UTF-8') . ' ' . mb_substr($seg, $qEnd, null, 'UTF-8'), ' -/,');
                } else {
                    $qty = null;
                    $clean = trim($seg);
                }
                if ($clean !== '') {
                    $out[] = ['text' => $clean, 'qty' => $qty];
                }
            }
        }
        return $out;
    }

    public static function detectAll(string $text): array
    {
        self::init();
        $codes = self::findCodes($text);
        $p = $codes[0] ?? null;
        [$shape, $cands, $ang] = self::detectShape($text);
        $out = [
            'code' => $p ? $p['code'] : '',
            'shape' => ($p ? $p['shape'] : $shape) ?: '',
            'shape_candidates' => $cands, 'angle' => $ang,
            'clearance' => ($p ? $p['relief'] : self::detectClearance($text)) ?: '',
            'size_code' => ($p ? $p['size_code'] : '') ?: '',
            'radius' => $p ? $p['corner_r'] : null,
            'ic_d' => $p ? $p['ic_d'] : null, 'thickness' => $p ? $p['thickness'] : null,
            'warnings' => $p ? $p['warnings'] : [],
        ];
        if ($out['size_code'] === '') {
            $sz = self::detectSize($text, $out['shape']);
            $out['size_code'] = $sz['size_code'] ?: '';
            $out['ic_d'] = $out['ic_d'] ?? $sz['ic_d'];
            $out['warnings'] = array_merge($out['warnings'], $sz['warnings'] ?? []);
        }
        if ($out['radius'] === null) {
            $out['radius'] = self::detectRadius($text);
        }
        if ($out['radius'] === null && !$p) {
            $m = [];
            if (preg_match('/(?<![0-9A-Z])(\d{2})(T\d|\d{2})(\d{2})(?![0-9])/u', self::normCode($text), $m)
                && isset(self::THICK[$m[2]]) && isset(self::$allSizeCodes[$m[1]])) {
                $out['radius'] = (int)$m[3] / 10.0;
            }
        }
        if (!$p && $out['code'] === '') {
            $m = [];
            if (preg_match('/' . self::PARTIAL_RE . '/u', self::normCode($text), $m, PREG_UNMATCHED_AS_NULL)) {
                $parts = [];
                for ($i = 1; $i <= 5; $i++) {
                    if (($m[$i] ?? null) !== null && $m[$i] !== '') {
                        $parts[] = $m[$i];
                    }
                }
                $out['code'] = implode('', $parts);
                $out['shape'] = $out['shape'] ?: $m[1];
                $out['clearance'] = $out['clearance'] ?: $m[2];
            }
        }
        if ($out['shape'] === '' && $cands) {
            $out['warnings'][] = 'Форма неоднозначна (' . implode('/', $cands) . ') — уточните угол при вершине';
        }
        return $out;
    }
}