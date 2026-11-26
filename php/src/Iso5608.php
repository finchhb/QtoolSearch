<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Детерминированный разбор кодов инструментальной оснастки ISO 5608 (без LLM).
 * Порт src/iso5608.py. Пластины/фрезы/свёрла/патроны не разбираются -> null.
 */
final class Iso5608
{
    public const EXTERNAL = 'external';
    public const BORING = 'boring';
    public const THREAD_EXTERNAL = 'thread_external';
    public const THREAD_INTERNAL = 'thread_internal';
    public const GROOVING_EXTERNAL = 'grooving_external';
    public const GROOVING_INTERNAL = 'grooving_internal';
    public const GROOVING_FACE = 'grooving_face';
    public const BLADE = 'blade';
    public const BLOCK = 'block';

    private const HANDS = ['L' => true, 'R' => true, 'N' => true];
    // отсортировано по длине по убыванию (как sorted(_THREAD_STYLES, key=len, reverse=True))
    private const THREAD_ALT = 'SCVER|SCVEL|SVNR|SVNL|CTTR|CTTL|SER|SEL|SNR|SNL|SWR|SWL';

    private static function mk(string $kind, array $kw = []): array
    {
        $out = [
            'kind' => $kind, 'clamp' => null, 'shape' => null, 'style' => null, 'clearance' => null,
            'hand' => null, 'shank_mm' => null, 'shank_width_mm' => null, 'shank_diameter_mm' => null,
            'length_letter' => null, 'insert_size' => null, 'insert_type' => null,
            'groove_width_mm' => null, 'groove_range_mm' => null, 'blade_height_mm' => null,
            'min_bore_mm' => null, 'length_mm' => null, 'series_key' => null, 'turning' => false,
        ];
        return array_merge($out, $kw);
    }

    private static function num(?string $text, ?float $default = null): ?float
    {
        if ($text === null) {
            return $default;
        }
        $t = str_replace(',', '.', $text);
        return is_numeric($t) ? (float)$t : $default;
    }

    private static function sizeCode(?string $text): ?string
    {
        $digits = preg_replace('/\D/', '', $text ?? '');
        return strlen($digits) >= 2 ? substr($digits, 0, 2) : null;
    }

    private static function styleLetters(string $style): array
    {
        $letters = str_split(preg_replace('/[^A-Za-z]/', '', $style));
        $n = count($letters);
        $hand = ($n >= 5 && isset(self::HANDS[$letters[4]])) ? $letters[4] : null;
        $clearance = $n >= 4 ? $letters[3] : null;
        if ($n === 4 && isset(self::HANDS[$letters[3]])) {
            $hand = $letters[3];
            $clearance = null;
        }
        return [
            'clamp' => $letters[0] ?? null,
            'shape' => $letters[1] ?? null,
            'style' => $letters[2] ?? null,
            'clearance' => $clearance,
            'hand' => $hand,
        ];
    }

    /** preg_match с семантикой Python re.match: неучаствующие группы -> null. */
    private static function rx(string $pattern, string $s): ?array
    {
        $m = [];
        if (preg_match('/' . $pattern . '/uD', $s, $m, PREG_UNMATCHED_AS_NULL) === 1) {
            return $m;
        }
        return null;
    }

    private static function parseOne(string $s): ?array
    {
        // блок и лезвия KGFH
        $m = self::rx('^KGFH-?(\d{2})(\d{2})-?(\d{2})(?:-?(.*))?$', $s);
        if ($m) {
            return self::mk(self::BLOCK, ['clamp' => 'K', 'shape' => 'G', 'style' => 'F', 'clearance' => 'H',
                'shank_mm' => (float)$m[1], 'shank_width_mm' => (float)$m[2],
                'blade_height_mm' => (float)$m[3], 'series_key' => 'KGFH-' . $m[3]]);
        }
        $m = self::rx('^KGFH-?(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?(.*))?$', $s);
        if ($m) {
            return self::mk(self::BLADE, ['clamp' => 'K', 'shape' => 'G', 'style' => 'F', 'clearance' => 'H',
                'blade_height_mm' => (float)$m[1], 'groove_width_mm' => self::num($m[2]),
                'series_key' => 'KGFH-' . $m[1] . '-' . $m[2]]);
        }
        // торцевые канавки KGFD
        $m = self::rx('^KGFD([LR])-?(\d{2})(\d{2})([A-Z])?-?(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?(.*))?$', $s);
        if ($m) {
            return self::mk(self::GROOVING_FACE, ['clamp' => 'K', 'shape' => 'G', 'style' => 'F', 'clearance' => 'D', 'hand' => $m[1],
                'shank_mm' => (float)$m[2], 'shank_width_mm' => (float)$m[3],
                'length_letter' => $m[4], 'groove_width_mm' => self::num($m[7]),
                'groove_range_mm' => $m[5] . '-' . $m[6], 'series_key' => 'KGFD-' . $m[7]]);
        }
        // наружные канавки KGD
        $m = self::rx('^KGD([LR])-?(\d{2})(\d{2})([A-Z])?-?(\d+)T(\d+)(?:-?(.*))?$', $s);
        if ($m) {
            return self::mk(self::GROOVING_EXTERNAL, ['clamp' => 'K', 'shape' => 'G', 'style' => 'D', 'hand' => $m[1],
                'shank_mm' => (float)$m[2], 'shank_width_mm' => (float)$m[3],
                'length_letter' => $m[4], 'groove_width_mm' => (float)$m[5], 'series_key' => 'KGD-' . $m[5]]);
        }
        // MGEH/MGEV
        $m = self::rx('^(MGEH|MGEV)([LR])(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9]*))?$', $s);
        if ($m) {
            return self::mk(self::GROOVING_EXTERNAL, ['clamp' => 'M', 'shape' => 'G', 'style' => 'E', 'clearance' => $m[1][3],
                'hand' => $m[2], 'shank_mm' => (float)$m[3], 'shank_width_mm' => (float)$m[4],
                'groove_width_mm' => self::num($m[5]), 'series_key' => $m[1] . '-' . $m[5]]);
        }
        $m = self::rx('^MGIV([LR])(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9]*))?$', $s);
        if ($m) {
            return self::mk(self::GROOVING_INTERNAL, ['clamp' => 'M', 'shape' => 'G', 'style' => 'I', 'clearance' => 'V',
                'hand' => $m[1], 'shank_mm' => (float)$m[2], 'shank_width_mm' => (float)$m[3],
                'groove_width_mm' => self::num($m[4]), 'series_key' => 'MGIV-' . $m[4]]);
        }
        // TTER/TTEL
        $m = self::rx('^TTE([LR])(\d{2})(\d{2})-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9]*))?$', $s);
        if ($m) {
            return self::mk(self::GROOVING_EXTERNAL, ['clamp' => 'T', 'shape' => 'T', 'style' => 'E', 'hand' => $m[1],
                'shank_mm' => (float)$m[2], 'shank_width_mm' => (float)$m[3],
                'groove_width_mm' => self::num($m[4]), 'series_key' => 'TTE-' . $m[4]]);
        }
        $m = self::rx('^QEKS(\d{2})(\d{2})([A-Z])?-?(\d{2})$', $s);
        if ($m) {
            return self::mk(self::GROOVING_EXTERNAL, ['clamp' => 'Q', 'shape' => 'E', 'style' => 'K',
                'shank_mm' => (float)$m[1], 'shank_width_mm' => (float)$m[2],
                'length_letter' => $m[3], 'insert_size' => $m[4], 'series_key' => 'QEK-' . $m[4]]);
        }
        // CGBL/CGBR
        $m = self::rx('^CGB([LR])(\d{2})(\d{2})([A-Z])?-?(\d{2})$', $s);
        if ($m) {
            return self::mk(self::GROOVING_EXTERNAL, ['clamp' => 'C', 'shape' => 'G', 'style' => 'B', 'hand' => $m[1],
                'shank_mm' => (float)$m[2], 'shank_width_mm' => (float)$m[3],
                'length_letter' => $m[4], 'insert_size' => $m[5], 'series_key' => 'CGB-' . $m[5]]);
        }
        // KTGFR/KTGFSL
        $m = self::rx('^KTGF([A-Z]?)([LR])(\d{2})(\d{2})([A-Z])?-?(\d{2})$', $s);
        if ($m) {
            return self::mk(self::GROOVING_EXTERNAL, ['clamp' => 'K', 'shape' => 'T', 'style' => 'G', 'clearance' => 'F', 'hand' => $m[2],
                'shank_mm' => (float)$m[3], 'shank_width_mm' => (float)$m[4],
                'length_letter' => $m[5], 'insert_size' => $m[6], 'series_key' => 'KTGF-' . $m[6]]);
        }
        // GQCR
        $m = self::rx('^GQC([LR])(\d{2})(\d{2})([A-Z])?-?(\d{2})(?:-(\d+))?$', $s);
        if ($m) {
            return self::mk(self::GROOVING_EXTERNAL, ['clamp' => 'G', 'shape' => 'Q', 'style' => 'C', 'hand' => $m[1],
                'shank_mm' => (float)$m[2], 'shank_width_mm' => (float)$m[3],
                'length_letter' => $m[4], 'insert_size' => $m[5], 'series_key' => 'GQC-' . $m[5]]);
        }
        // HNGR
        $m = self::rx('^HNG([LR])(\d{2})([A-Z])(\d{2})$', $s);
        if ($m) {
            return self::mk(self::GROOVING_INTERNAL, ['clamp' => 'H', 'shape' => 'N', 'style' => 'G', 'hand' => $m[1],
                'shank_diameter_mm' => (float)$m[2], 'length_letter' => $m[3],
                'insert_size' => $m[4], 'series_key' => 'HNG-' . $m[4]]);
        }
        // FGHH
        if (self::rx('^FGHH$', $s)) {
            return self::mk(self::GROOVING_FACE, ['clamp' => 'F', 'shape' => 'G', 'style' => 'H', 'clearance' => 'H', 'series_key' => 'FGHH']);
        }
        // борштанги EWB
        $m = self::rx('^EWB(\d{2})(\d{2})-?(\d{2,3})$', $s);
        if ($m) {
            return self::mk(self::BORING, ['clamp' => 'E', 'shape' => 'W', 'style' => 'B',
                'shank_diameter_mm' => (float)$m[1], 'length_mm' => (float)$m[3], 'series_key' => 'EWB-' . $m[1]]);
        }
        // резьбовые
        $m = self::rx('^(' . self::THREAD_ALT . ')-?(\d{2})(\d{2})([A-Z])?-?(\d{1,4})(?:-?([A-Z0-9-]*))?$', $s);
        if ($m) {
            $style = $m[1];
            $a = $m[2];
            $b = $m[3];
            $length = $m[4];
            $size = $m[5];
            $internal = $style[1] === 'N';
            $diameter = $a === '00' ? (float)$b : null;
            $shank = $diameter !== null ? null : (float)$a;
            $width = $diameter !== null ? null : (float)$b;
            $sizeCode = self::sizeCode($size);
            return self::mk($internal ? self::THREAD_INTERNAL : self::THREAD_EXTERNAL, [
                'clamp' => $style[0], 'shape' => $style[1], 'style' => substr($style, 2), 'hand' => $style[strlen($style) - 1],
                'shank_mm' => $shank, 'shank_width_mm' => $width, 'shank_diameter_mm' => $diameter,
                'length_letter' => $length, 'insert_size' => $sizeCode,
                'insert_type' => $sizeCode !== null ? $sizeCode . ($internal ? 'IR' : 'ER') : null,
                'series_key' => $style . '-' . ($sizeCode ?? $size),
            ]);
        }
        // расточные
        $m = self::rx('^([SCEH])(\d{2})(\d{2})?([A-Z])-?([A-Z0-9]{2,6}?)-?(\d{1,4}(?:[.,]\d+)?)(?:-?([A-Z0-9-]*))?$', $s);
        if ($m) {
            $base = $m[5];
            $letters = self::styleLetters($base);
            $minBore = null;
            if ($m[7]) {
                $a = self::rx('^A(\d{1,3})$', $m[7]);
                if ($a) {
                    $minBore = (float)$a[1];
                }
            }
            $sizeCode = self::sizeCode($m[6]);
            $width = null;
            $kind = self::BORING;
            $insertType = null;
            if (str_starts_with($base, 'KGI')) {
                $kind = self::GROOVING_INTERNAL;
                $width = self::num($m[6]);
                $sizeCode = null;
            } elseif (str_starts_with($base, 'CTT')) {
                $kind = self::THREAD_EXTERNAL;
                $insertType = $sizeCode !== null ? $sizeCode . 'ER' : null;
            }
            return self::mk($kind, array_merge($letters, [
                'shank_diameter_mm' => (float)$m[2], 'length_letter' => $m[4],
                'insert_size' => $sizeCode, 'insert_type' => $insertType,
                'groove_width_mm' => $width, 'min_bore_mm' => $minBore,
                'series_key' => substr($base, 0, 4) . '-' . ($sizeCode ?? $m[6]),
                'turning' => $kind === self::BORING,
            ]));
        }
        // наружные державки
        $m = self::rx('^([A-Z]{4})([LRN])-?(\d{2})(\d{2})([A-Z])?-?(\d{1,4})?(?:-?([A-Z0-9-]*))?$', $s);
        if ($m) {
            $size = self::sizeCode($m[6]);
            return self::mk(self::EXTERNAL, ['clamp' => $m[1][0], 'shape' => $m[1][1], 'style' => $m[1][2],
                'clearance' => $m[1][3], 'hand' => $m[2],
                'shank_mm' => (float)$m[3], 'shank_width_mm' => (float)$m[4],
                'length_letter' => $m[5], 'insert_size' => $size,
                'series_key' => $m[1] . '-' . ($size ?? $m[6] ?? '?'), 'turning' => true]);
        }
        return null;
    }

    public static function parseHolderCode(?string $code): ?array
    {
        if ($code === null || $code === '') {
            return null;
        }
        foreach (Normalize::codeVariants($code) as $variant) {
            $norm = Normalize::normalizeSeparators(mb_strtoupper($variant, 'UTF-8'));
            $parsed = self::parseOne($norm);
            if ($parsed) {
                $parsed['code'] = $norm;
                return $parsed;
            }
        }
        return null;
    }
}