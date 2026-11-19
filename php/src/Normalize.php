<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Нормализация: регистр, омоглифы кириллица/латиница, неверная раскладка,
 * разделители, десятичная запятая, расстояние Дамерау-Левенштейна.
 * Порт src/code_normalize.py + нормализационных функций src/catalog_search.py.
 */
final class Normalize
{
    /** Раскладка ЙЦУКЕН -> QWERTY (побуквенно, нижний регистр). */
    private const RU_TO_EN = [
        'й' => 'q', 'ц' => 'w', 'у' => 'e', 'к' => 'r', 'е' => 't', 'н' => 'y', 'г' => 'u', 'ш' => 'i', 'щ' => 'o', 'з' => 'p',
        'х' => '[', 'ъ' => ']', 'ф' => 'a', 'ы' => 's', 'в' => 'd', 'а' => 'f', 'п' => 'g', 'р' => 'h', 'о' => 'j', 'л' => 'k',
        'д' => 'l', 'ж' => ';', 'э' => "'", 'я' => 'z', 'ч' => 'x', 'с' => 'c', 'м' => 'v', 'и' => 'b', 'т' => 'n', 'ь' => 'm',
        'б' => ',', 'ю' => '.',
    ];

    /** Омоглифы: кириллическая буква, выглядящая как латинская (регистр сохраняется). */
    private const HOMOGLYPHS = [
        'а' => 'a', 'в' => 'b', 'е' => 'e', 'к' => 'k', 'м' => 'm', 'н' => 'h', 'о' => 'o', 'р' => 'p', 'с' => 'c', 'т' => 't',
        'у' => 'y', 'х' => 'x', 'А' => 'A', 'В' => 'B', 'Е' => 'E', 'К' => 'K', 'М' => 'M', 'Н' => 'H', 'О' => 'O', 'Р' => 'P',
        'С' => 'C', 'Т' => 'T', 'У' => 'Y', 'Х' => 'X',
    ];

    /** Кириллица по буквам кода: «РПМТ» -> RPMT (регистр сохраняется). */
    private const RU_CODE_LETTERS = [
        'а' => 'a', 'в' => 'v', 'г' => 'g', 'д' => 'd', 'е' => 'e', 'ж' => 'zh', 'з' => 'z', 'и' => 'i', 'й' => 'j',
        'к' => 'k', 'л' => 'l', 'м' => 'm', 'н' => 'n', 'о' => 'o', 'п' => 'p', 'р' => 'r', 'с' => 'c', 'т' => 't',
        'у' => 'y', 'ф' => 'f', 'х' => 'x', 'ц' => 'c', 'ч' => 'ch', 'ш' => 'sh', 'щ' => 'sch', 'ъ' => '', 'ы' => 'y',
        'ь' => '', 'э' => 'e', 'ю' => 'yu', 'я' => 'ya',
    ];

    public static function lower(string $s): string
    {
        return mb_strtolower($s, 'UTF-8');
    }

    /** lower + ё -> е (как в Python .lower().replace("ё","е")). */
    public static function low(string $s): string
    {
        return str_replace('ё', 'е', self::lower($s));
    }

    public static function layoutToLatin(string $s): string
    {
        $s = self::lower($s);
        $out = '';
        foreach (mb_str_split($s, 1, 'UTF-8') as $ch) {
            $out .= self::RU_TO_EN[$ch] ?? $ch;
        }
        return $out;
    }

    public static function homoglyphLatin(string $s): string
    {
        $out = '';
        foreach (mb_str_split($s, 1, 'UTF-8') as $ch) {
            $out .= self::HOMOGLYPHS[$ch] ?? $ch;
        }
        return $out;
    }

    public static function cyrillicCodeLetters(string $s): string
    {
        $out = '';
        foreach (mb_str_split($s, 1, 'UTF-8') as $ch) {
            $low = mb_strtolower($ch, 'UTF-8');
            if (isset(self::RU_CODE_LETTERS[$low])) {
                $tr = self::RU_CODE_LETTERS[$low];
                $out .= self::isUpper($ch) ? mb_strtoupper($tr, 'UTF-8') : $tr;
            } else {
                $out .= $ch;
            }
        }
        return $out;
    }

    private static function isUpper(string $ch): bool
    {
        return $ch !== mb_strtolower($ch, 'UTF-8') && $ch === mb_strtoupper($ch, 'UTF-8');
    }

    /** Варианты кода: омоглифы первыми, затем как есть, побуквенно, раскладка. */
    public static function codeVariants(string $s): array
    {
        $base = trim($s);
        $out = [];
        foreach ([self::homoglyphLatin($base), $base, self::cyrillicCodeLetters($base), self::layoutToLatin($base)] as $v) {
            if ($v !== '' && !in_array($v, $out, true)) {
                $out[] = $v;
            }
        }
        return $out;
    }

    /** Пробелы и тире -> «-», повторные дефисы схлопываются. */
    public static function normalizeSeparators(string $s): string
    {
        $out = preg_replace('/[\s\x{2013}\x{2014}]+/u', '-', trim($s));
        $out = preg_replace('/-{2,}/', '-', $out);
        return trim($out, '-');
    }

    /** compact: lower, оставить только [a-z0-9а-я] (ё выпадает, как в Python). */
    private static array $compactRe = [];
    public static function compact(string $s): string
    {
        if (!isset(self::$compactRe[0])) {
            self::$compactRe[0] = '/[^a-z0-9а-я]/u';
        }
        return preg_replace(self::$compactRe[0], '', self::lower($s));
    }

    /** Варианты написания запроса: как есть, омоглифы, побуквенно, раскладка. */
    public static function queryVariants(string $q): array
    {
        $base = self::low($q);
        $out = [];
        foreach ([$base, self::homoglyphLatin($base), self::cyrillicCodeLetters($base), self::layoutToLatin($base)] as $v) {
            if (!in_array($v, $out, true)) {
                $out[] = $v;
            }
        }
        return $out;
    }

    public static function tokenize(string $text): array
    {
        preg_match_all('/[a-zа-я0-9]+(?:[.,\/][a-zа-я0-9]+)*/u', self::low($text), $m);
        return $m[0];
    }

    /** O/О/Q между цифрами -> 0; l/I/| между цифрами -> 1. */
    public static function fixDigitLetters(string $s): string
    {
        $s = preg_replace('/(?<=\d)[OОQ](?=\d)/u', '0', $s);
        return preg_replace('/(?<=\d)[lI|](?=\d)/u', '1', $s);
    }

    /** Число для показа: 8.5 -> «8,5», 90.0 -> «90». */
    public static function fmtNum($value): string
    {
        if (is_float($value)) {
            $s = self::gFormat($value);
            return str_replace('.', ',', $s);
        }
        return (string)$value;
    }

    /** Аналог Python f"{value:g}" (6 значащих цифр, без хвостовых нулей). */
    public static function gFormat(float $value): string
    {
        if ($value == 0.0) {
            return '0';
        }
        $s = sprintf('%.6G', $value);
        // %.6G может дать экспоненту для очень больших/малых; для наших диапазонов не нужно
        if (stripos($s, 'E') !== false) {
            $s = rtrim(rtrim(sprintf('%.10F', $value), '0'), '.');
        }
        return $s;
    }

    /** fullmatch: вся строка должна совпасть с шаблоном. */
    private static array $fullmatchRe = [];
    public static function fullmatch(string $pattern, string $subject): bool
    {
        $key = $pattern;
        if (!isset(self::$fullmatchRe[$key])) {
            self::$fullmatchRe[$key] = '/^(?:' . $pattern . ')$/uD';
        }
        return preg_match(self::$fullmatchRe[$key], $subject) === 1;
    }

    /** Расстояние Дамерау-Левенштейна с ранним выходом. */
    public static function damerau(string $a, string $b, int $maxDist = 1): int
    {
        if ($a === $b) {
            return 0;
        }
        $ca = mb_str_split($a, 1, 'UTF-8');
        $cb = mb_str_split($b, 1, 'UTF-8');
        $la = count($ca);
        $lb = count($cb);
        if (abs($la - $lb) > $maxDist) {
            return $maxDist + 1;
        }
        $prev2 = [];
        $prev = range(0, $lb);
        for ($i = 1; $i <= $la; $i++) {
            $cur = array_fill(0, $lb + 1, 0);
            $cur[0] = $i;
            $best = $cur[0];
            for ($j = 1; $j <= $lb; $j++) {
                $cost = $ca[$i - 1] === $cb[$j - 1] ? 0 : 1;
                $cur[$j] = min($prev[$j] + 1, $cur[$j - 1] + 1, $prev[$j - 1] + $cost);
                if ($i > 1 && $j > 1 && $ca[$i - 1] === $cb[$j - 2] && $ca[$i - 2] === $cb[$j - 1]) {
                    $cur[$j] = min($cur[$j], $prev2[$j - 2] + 1);
                }
                if ($cur[$j] < $best) {
                    $best = $cur[$j];
                }
            }
            if ($best > $maxDist) {
                return $maxDist + 1;
            }
            $prev2 = $prev;
            $prev = $cur;
        }
        return $prev[$lb];
    }

    /** Материал обработки -> группа ISO (порядок важен). */
    public static function materialIso(string $text): ?string
    {
        $low = self::low($text);
        $rules = [
            ['титан|жаропроч|инконель|inconel|хастеллой|нимоник', 'S'],
            ['нержав|12х18|08х18|10х17|14х17|20х13|40х13|aisi\s?3\d\d|aisi\s?4\d\d', 'M'],
            ['чугун|вч\d|сч\d|кч\d', 'K'],
            ['алюмин|дюрал|латун|бронз|мед[ьи]|цинк', 'N'],
            ['закал|цемент|hrc\s?\d|твердост', 'H'],
            ['стал[ьи]|конструкцион|углеродист|40х|45х|20х|30х|18хгт|40хн', 'P'],
        ];
        foreach ($rules as [$pattern, $iso]) {
            if (preg_match('/' . $pattern . '/u', $low)) {
                return $iso;
            }
        }
        return null;
    }

    public static function operationFromText(string $text): ?string
    {
        $low = self::low($text);
        foreach ([['получистов', 'semi_finishing'], ['чистов', 'finishing'], ['чернов', 'roughing']] as [$pattern, $op]) {
            if (preg_match('/' . $pattern . '/u', $low)) {
                return $op;
            }
        }
        return null;
    }

    /** Разговорные синонимы (барпулер -> барпуллер). */
    public static function applyAliases(string $text): string
    {
        $out = $text;
        foreach (['барпулер' => 'барпуллер'] as $src => $dst) {
            $out = preg_replace('/(?<![a-zа-яё])' . $src . '/iu', $dst, $out);
        }
        return $out;
    }
}