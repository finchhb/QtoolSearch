<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Извлечение кодов пластин и державок из текста запроса/названия.
 * Порт insert_prefix_from_word / insert_code_from_text / holder_code_from_text
 * и связанных констант из src/catalog_search.py.
 */
final class Codes
{
    public const HOLDER_PREFIXES = [
        'PCLN' => true, 'MCLN' => true, 'PWLN' => true, 'MWLN' => true, 'PTGN' => true, 'MTGN' => true,
        'PDJN' => true, 'MDJN' => true, 'MVJN' => true, 'PVJN' => true, 'PSSN' => true, 'MSSN' => true,
        'SCLC' => true, 'SDJC' => true, 'STGC' => true, 'SVJB' => true, 'SVJC' => true, 'SDUC' => true,
    ];
    public const INSERT_SHAPES = 'ABCDEHKLMOPRSTVW';
    public const ISO_CLEARANCE = 'ABCDEFGNP';

    public const COMMON_INSERT_PREFIXES = [
        'CNMG' => true, 'DNMG' => true, 'VNMG' => true, 'WNMG' => true, 'TNMG' => true, 'SNMG' => true, 'KNMX' => true, 'KNUX' => true,
        'CCMT' => true, 'DCMT' => true, 'VCMT' => true, 'TCMT' => true, 'SCMT' => true, 'CCGT' => true, 'DCGT' => true, 'VCGT' => true, 'TCGT' => true,
        'APMT' => true, 'APKT' => true, 'APHT' => true, 'SEKT' => true, 'SEKR' => true, 'SPKN' => true, 'SPMT' => true, 'XDLT' => true,
        'RPMT' => true, 'RDMW' => true, 'RDMT' => true, 'LNMU' => true, 'LNMT' => true, 'SDMT' => true, 'EPNW' => true, 'WNMU' => true,
        'MGMN' => true, 'ZQMX' => true, '16ER' => true, '16IR' => true, '22ER' => true, '22IR' => true,
    ];

    // B11: буквенные ключи групп стружколомов (из analogs_engine.py CHIPBREAKER_GROUPS)
    public const CHIPBREAKER_PREFIXES = [
        'PF'=>true,'GF'=>true,'HQ'=>true,'EF'=>true,'PM'=>true,'PMK'=>true,'CQ'=>true,'QM'=>true,
        'MM'=>true,'MJ'=>true,'MP'=>true,'MT'=>true,'GM'=>true,'SM'=>true,'EM'=>true,'PR'=>true,
        'ZR'=>true,'GS'=>true,'GR'=>true,'HR'=>true,'DR'=>true,'MR'=>true,'NF'=>true,'AL'=>true,
        'HA'=>true,'MB'=>true,'UC'=>true,'KM'=>true,
    ];

    public const PLATE_SHAPE_WORDS = [
        ['ромб', 'C'], ['квадрат', 'S'], ['треугольн', 'T'], ['круг|округл|раунд', 'R'],
        ['пятиугольн', 'P'], ['шестиугольн', 'H'], ['параллелограмм', 'A'], ['восьмиугольн', 'O'],
    ];
    public const PLATE_SHAPE_TITLES = [
        'C' => 'ромб', 'S' => 'квадрат', 'T' => 'треугольник', 'R' => 'круг',
        'P' => 'пятиугольник', 'H' => 'шестиугольник', 'A' => 'параллелограмм', 'O' => 'восьмиугольник',
    ];

    public static function isShape(string $ch): bool
    {
        return $ch !== '' && str_contains(self::INSERT_SHAPES, $ch);
    }

    /** «РПМТ», «APMT», «СТМН» -> латинский префикс пластины (или null). */
    public static function insertPrefixFromWord(string $raw, array $known = []): ?string
    {
        $cands = [];
        foreach ([Normalize::cyrillicCodeLetters($raw), Normalize::cyrillicCodeLetters(Normalize::homoglyphLatin($raw)), Normalize::homoglyphLatin($raw)] as $w) {
            $w = mb_strtoupper($w, 'UTF-8');
            if (!in_array($w, $cands, true)) {
                $cands[] = $w;
            }
        }
        foreach ($cands as $w) {
            if (Normalize::fullmatch('[A-Z]{2,5}', $w) && self::isShape($w[0]) && (isset($known[$w]) || isset(self::COMMON_INSERT_PREFIXES[$w]))) {
                return $w;
            }
        }
        foreach ($cands as $w) {
            if (Normalize::fullmatch('[A-Z]{2,5}', $w) && self::isShape($w[0])) {
                return $w;
            }
        }
        return null;
    }

    /** CNMG 12 04 08 / CNMG120408 -> CNMG120408. Хвост из букв (стружколом) не приклеиваем. */
    public static function insertCodeFromText(string $text): ?string
    {
        $src = mb_strtoupper(Normalize::cyrillicCodeLetters(Normalize::low($text)), 'UTF-8');
        $toks = [];
        preg_match_all('/[A-Z0-9]+/u', Normalize::fixDigitLetters($src), $toks);
        $toks = $toks[0];
        $n = count($toks);
        for ($i = 0; $i < $n; $i++) {
            $tok = $toks[$i];
            // B4: склеенный код+марка / лишняя цифра: CNMG120408PM4325, CNMG1204084325, CNMG1204088
            if (Normalize::fullmatch('[A-Z]{2,5}\d{6}(?:[A-Z]{1,4}\d{2,4}|\d{1,4})', $tok)) {
                preg_match('/^([A-Z]{2,5})(\d{6})/u', $tok, $m);
                $code = $m[1] . $m[2];
                if (self::isShape($m[1][0]) && Iso5608::parseHolderCode($code) === null) {
                    return $code;   // хвост (PM4325/4325/8) НЕ приклеиваем
                }
            }
            if (Normalize::fullmatch('[A-Z]{2,5}\d{4,6}[A-Z]{0,4}', $tok)) {
                if (self::isShape($tok[0]) && Iso5608::parseHolderCode($tok) === null) {
                    return $tok;
                }
                continue;
            }
            if (Normalize::fullmatch('[A-Z]{2,5}', $tok)) {
                if (!self::isShape($tok[0]) || isset(self::HOLDER_PREFIXES[substr($tok, 0, 4)])) {
                    continue;
                }
                $digits = '';
                $j = $i + 1;
                while ($j < $n && Normalize::fullmatch('\d{1,6}', $toks[$j]) && strlen($digits) < 6) {
                    if (strlen($digits) + strlen($toks[$j]) > 6) {
                        break;
                    }
                    $digits .= $toks[$j];
                    $j++;
                }
                if (strlen($digits) >= 4 && strlen($digits) <= 6) {
                    $code = $tok . $digits;
                    if (Iso5608::parseHolderCode($code) === null) {
                        return $code;
                    }
                }
            }
        }
        return null;
    }

    /** PCLNR 2525 M12 / SNR0006K06-A12 -> компактный код с сохранением дефиса. */
    public static function holderCodeFromText(string $text): ?string
    {
        $toks = [];
        preg_match_all('/[A-Za-zА-Яа-яЁё0-9-]+/u', $text, $toks);
        $toks = $toks[0];
        $n = count($toks);
        for ($i = 0; $i < $n; $i++) {
            $letters = Normalize::homoglyphLatin($toks[$i]);
            if (preg_match('/[^A-Za-z0-9-]/u', $letters)) {
                continue;
            }
            $cand = strtoupper($letters);
            if (Iso5608::parseHolderCode($cand) !== null) {
                return $cand;
            }
            if (Normalize::fullmatch('[A-Z]{1,6}', $cand)) {
                $digits = '';
                $j = $i + 1;
                while ($j < $n && strlen($digits) < 8) {
                    $nxt = strtoupper(Normalize::homoglyphLatin($toks[$j]));
                    if (Normalize::fullmatch('\d{1,4}|[A-Z]\d{1,3}|\d{2,5}[A-Z]\d{1,3}', $nxt)) {
                        $digits .= $nxt;
                        $j++;
                    } else {
                        break;
                    }
                }
                if ($digits !== '' && Iso5608::parseHolderCode($cand . $digits) !== null) {
                    return $cand . $digits;
                }
            }
        }
        return null;
    }
}