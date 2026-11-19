<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Детерминированный поиск по каталогу (без LLM). Порт CatalogSearchEngine из src/catalog_search.py.
 * Слои: индексы (df/vocab/префиксы), фильтры-лесенка, скоринг, дедуп, порядок брендов.
 */
final class CatalogSearch
{
    public const FAMILY_TITLES = [
        'insert' => 'пластины', 'drill' => 'сверла', 'mill' => 'фрезы', 'tap' => 'метчики',
        'die' => 'плашки', 'reamer' => 'развертки', 'countersink' => 'зенковки и фаскосниматели',
        'holder' => 'державки и резцы', 'accessory' => 'оснастка и крепеж',
        'measuring' => 'измерительный инструмент', 'saw' => 'пилы и диски',
    ];
    public const BRAND_PRIORITY = ['ZZKLT', 'DESKAR', 'OLICNC', 'ZEGYO'];

    /** @var array<string,int> */
    private static array $brandRank = [];
    /** @var array<string,true> */
    private static array $commonPrefixSet = [];

    /** @var list<array<string,mixed>> */
    public array $items = [];
    /** @var array<string,list<array<string,mixed>>> */
    public array $byFamily = [];
    /** @var array<string,int> */
    public array $df = [];
    public int $total = 0;
    /** @var array<string,true> */
    private array $vocab = [];
    /** @var array<int,list<string>> */
    private array $vocabByLen = [];
    /** @var array<string,?string> */
    private array $corrCache = [];
    /** @var array<string,int> */
    public array $insertPrefixes = [];

    /** @var array<string,list<int>> compact(code) → item uids */
    private array $byCode = [];
    /** @var array<string,list<int>> prefix4 → item uids */
    private array $byPrefix = [];
    /** @var array<string,list<int>> token → item uids (инвертированный индекс) */
    private array $byToken = [];

    public function __construct(?array $items = null)
    {
        if (self::$brandRank === []) {
            foreach (self::BRAND_PRIORITY as $i => $b) {
                self::$brandRank[strtolower($b)] = $i;
            }
        }
        if (self::$commonPrefixSet === []) {
            foreach (Codes::COMMON_INSERT_PREFIXES as $p) {
                self::$commonPrefixSet[$p] = true;
            }
        }
        if ($items) {
            $this->load($items);
        }
    }

    // ---- загрузка и индексы ----------------------------------------------------------------------
    public function load(array $items): void
    {
        $this->items = [];
        $this->byFamily = [];
        $df = [];
        $vocab = [];
        $prefixes = [];
        $uid = 0;
        foreach ($items as $it) {
            $fam = $it['family'] ?? '';
            if (!$fam || $fam === 'other') {
                continue;
            }
            $attrs = $it['attrs'] ?? [];
            if (!is_array($attrs)) {
                $attrs = [];
            }
            $iso = strtoupper(trim((string)($attrs['iso_code'] ?? '')));
            if (strlen($iso) >= 4) {
                $p4 = substr($iso, 0, 4);
                $prefixes[$p4] = ($prefixes[$p4] ?? 0) + 1;
            }
            if ($fam === 'holder') {
                $hc = !empty($attrs['holder_code']) ? $attrs['holder_code'] : ($it['sku'] ?? '');
                $info = Compat::holderInsertCompat((string)$hc);
                if ($info) {
                    $it['_insert_compat'] = $info;
                    $dia = $info['shank_diameter_mm'] ?? null;
                    if (!empty($dia)) {
                        $attrs['shank_mm'] = $dia;
                        $attrs['shank_diameter_mm'] = $dia;
                        unset($attrs['shank_section']);
                    } elseif (!empty($info['shank_mm']) && empty($attrs['shank_mm'])) {
                        $attrs['shank_mm'] = $info['shank_mm'];
                        $side = (int)$info['shank_mm'];
                        if (!isset($attrs['shank_section'])) {
                            $attrs['shank_section'] = $side . '×' . $side;
                        }
                    }
                }
            } elseif ($fam === 'mill') {
                $codes = Compat::millInsertCodes((string)($it['name'] ?? ''));
                if ($codes) {
                    $it['_mill_inserts'] = $codes;
                    $attrs['compatible_inserts'] = implode(', ', $codes);
                }
            } elseif ($fam === 'accessory' && ($it['category'] ?? '') === 'tool_holder') {
                $m = [];
                if (preg_match('/SBHA\)?\s*(\d{2})\s*[-–]\s*(\d{2})(?:\s*[-–]\s*(\d{2,3}))?/u', mb_strtoupper((string)($it['name'] ?? ''), 'UTF-8'), $m, PREG_UNMATCHED_AS_NULL) === 1) {
                    if (!isset($attrs['shank_mm'])) {
                        $attrs['shank_mm'] = (float)$m[1];
                    }
                    if (!isset($attrs['clamp_mm'])) {
                        $attrs['clamp_mm'] = (float)$m[2];
                    }
                    if (($m[3] ?? null) !== null && $m[3] !== '' && !isset($attrs['length_mm'])) {
                        $attrs['length_mm'] = (float)$m[3];
                    }
                }
            }
            $it['attrs'] = $attrs;
            $parts = [];
            foreach ([$it['sku'] ?? '', $it['name'] ?? '', $it['brand'] ?? '', $it['category'] ?? '',
                $attrs['iso_code'] ?? '', $attrs['holder_code'] ?? '', $attrs['grade'] ?? '',
                $attrs['thread'] ?? '', $attrs['coating'] ?? '', $attrs['standard'] ?? ''] as $x) {
                if (!empty($x)) {
                    $parts[] = (string)$x;
                }
            }
            $text = implode(' ', $parts);
            $toks = [];
            foreach (Normalize::tokenize($text) as $t) {
                $toks[$t] = true;
            }
            $it['_tokens'] = $toks;
            $it['_compact'] = Normalize::compact(($it['sku'] ?? '') . ' ' . ($it['name'] ?? ''));
            $it['_name_norm'] = Normalize::compact(Normalize::homoglyphLatin((string)($it['name'] ?? '')));
            $codeParts = [];
            foreach ([$it['sku'] ?? '', $attrs['iso_code'] ?? '', $attrs['holder_code'] ?? ''] as $x) {
                if (!empty($x)) {
                    $codeParts[] = (string)$x;
                }
            }
            $it['_code_compact'] = Normalize::compact(implode(' ', $codeParts));
            $it['_brand_norm'] = Normalize::compact((string)($it['brand'] ?? ''));
            $it['_uid'] = $uid++;
            // S2/S5: индексы кодов и токенов
            $cc = $it['_code_compact'] ?? '';
            if ($cc !== '') {
                if (!isset($this->byCode[$cc])) {
                    $this->byCode[$cc] = [];
                }
                $this->byCode[$cc][] = $it['_uid'];
                $p4 = mb_substr($cc, 0, 4, 'UTF-8');
                if ($p4 !== '') {
                    if (!isset($this->byPrefix[$p4])) {
                        $this->byPrefix[$p4] = [];
                    }
                    $this->byPrefix[$p4][] = $it['_uid'];
                }
            }
            foreach ($toks as $t => $_) {
                $t = (string)$t;
                if (!isset($this->byToken[$t])) {
                    $this->byToken[$t] = [];
                }
                $this->byToken[$t][] = $it['_uid'];
                $df[$t] = ($df[$t] ?? 0) + 1;
                if (mb_strlen($t, 'UTF-8') >= 4 && preg_match('/\d/u', $t) === 1) {
                    $vocab[$t] = true;
                }
            }
            $this->byFamily[$fam][] = $it;
            $this->items[] = $it;
        }
        $this->df = $df;
        $this->total = count($this->items);
        $this->vocab = $vocab;
        $this->insertPrefixes = $prefixes;
        $byLen = [];
        foreach ($vocab as $t => $_) {
            $t = (string)$t;
            $byLen[mb_strlen($t, 'UTF-8')][] = $t;
        }
        foreach ($byLen as $len => $list) {
            sort($list, SORT_STRING);
            $byLen[$len] = $list;
        }
        $this->vocabByLen = $byLen;
        $this->corrCache = [];
    }

    // ---- утилиты ---------------------------------------------------------------------------------
    private function idf(string $tok): float
    {
        $df = $this->df[$tok] ?? 0;
        return $this->total ? log(($this->total - $df + 0.5) / ($df + 0.5) + 1.0) : 0.0;
    }

    private function textScore(array $it, array $tokens, array $correctable = []): float
    {
        if (!$tokens) {
            return 0.0;
        }
        $doc = $it['_tokens'] ?? [];
        $score = 0.0;
        foreach ($tokens as $t) {
            if (isset($doc[$t])) {
                $score += $this->idf($t);
            } elseif (isset($correctable[$t])) {
                $fixed = $this->correct($t);
                if ($fixed !== null && isset($doc[$fixed])) {
                    $score += $this->idf($fixed) * 0.6;
                }
            }
        }
        return $score;
    }

    private function correct(string $tok): ?string
    {
        if (array_key_exists($tok, $this->corrCache)) {
            return $this->corrCache[$tok];
        }
        $result = null;
        if (isset($this->vocab[$tok])) {
            $result = $tok;
        } elseif (mb_strlen($tok, 'UTF-8') >= 5) {
            $len = mb_strlen($tok, 'UTF-8');
            foreach ([$len - 1, $len, $len + 1] as $length) {
                foreach ($this->vocabByLen[$length] ?? [] as $cand) {
                    if (Normalize::damerau($tok, $cand) <= 1) {
                        $result = $cand;
                        break;
                    }
                }
                if ($result !== null) {
                    break;
                }
            }
        }
        $this->corrCache[$tok] = $result;
        return $result;
    }

    public function canonicalInsertCode(string $code): string
    {
        if ($code === '' || mb_strlen($code, 'UTF-8') < 4) {
            return $code;
        }
        $pref = strtoupper(mb_substr($code, 0, 4, 'UTF-8'));
        if (isset($this->insertPrefixes[$pref]) || isset(self::$commonPrefixSet[$pref])) {
            return $code;
        }
        $cands = [];
        foreach ($this->insertPrefixes as $known => $cnt) {
            if ($known[0] !== $pref[0]) {
                continue;
            }
            $dist = Normalize::damerau($pref, $known, 2);
            if ($dist <= 2) {
                $cands[] = [$dist, -$cnt, $known];
            }
        }
        if (!$cands) {
            return $code;
        }
        usort($cands, static fn($x, $y) => ($x[0] <=> $y[0]) ?: ($x[1] <=> $y[1]) ?: strcmp($x[2], $y[2]));
        return $cands[0][2] . mb_substr($code, 4, null, 'UTF-8');
    }

    /** @return array{0:int,1:string} */
    public static function codeMatch(array $item, string $code): array
    {
        $want = Normalize::compact($code);
        if ($want === '') {
            return [0, ''];
        }
        $attrs = $item['attrs'] ?? [];
        $iso = Normalize::compact((string)($attrs['iso_code'] ?? ''));
        if ($iso !== '' && $iso === $want) {
            return [3, 'код'];
        }
        if (Normalize::compact((string)($attrs['holder_code'] ?? '')) === $want) {
            return [3, 'код'];
        }
        $sku = Normalize::compact((string)($item['sku'] ?? ''));
        if (str_starts_with($sku, $want)) {
            $after = mb_substr($sku, mb_strlen($want, 'UTF-8'), 1, 'UTF-8');
            return ctype_digit($after) ? [1, 'часть кода'] : [3, 'код'];
        }
        if ($iso !== '' && str_contains($iso, $want)) {
            return [1, 'часть кода'];
        }
        $have = $item['_code_compact'] ?? '';
        if ($have !== '' && str_contains($have, $want)) {
            return [2, 'код'];
        }
        return [0, ''];
    }

    // ---- фильтры ---------------------------------------------------------------------------------
    /** @return list<array{0:string,1:bool,2:\Closure}> */
    private function filters(Query $q, string $fam): array
    {
        $a = $q->attrs;
        $out = [];
        if ($fam === 'insert') {
            if ($q->insert_code) {
                $wantCode = $a['insert_prefix'] ?? $q->insert_code;
                $out[] = ['код', true, fn(array $it): bool => self::codeMatch($it, $wantCode)[0] > 0];
            }
            if ($q->holder_compat) {
                $out[] = ['под державку', true, fn(array $it): bool => self::insertFitsHolder($it, $q)];
            }
            if (!empty($a['iso_tail'])) {
                $wantIso = Normalize::compact($q->insert_code . $a['iso_tail']);
                $out[] = ['полный код', true, fn(array $it): bool => Normalize::compact((string)(($it['attrs'] ?? [])['iso_code'] ?? '')) === $wantIso];
            }
            if (!empty($a['size_code'])) {
                $wantSize = str_pad((string)$a['size_code'], 2, '0', STR_PAD_LEFT);
                $out[] = ['размер', true, fn(array $it): bool => str_pad((string)(($it['attrs'] ?? [])['size_code'] ?? ''), 2, '0', STR_PAD_LEFT) === $wantSize];
            }
            if (!empty($a['plate_shape'])) {
                $wantShape = $a['plate_shape'];
                $out[] = ['форма', true, fn(array $it): bool => strtoupper((string)(($it['attrs'] ?? [])['insert_shape'] ?? '')) === $wantShape];
            }
            if (!empty($a['plate_size'])) {
                $wantPlate = $a['plate_size'];
                $out[] = ['размер', true, fn(array $it): bool => str_pad((string)(($it['attrs'] ?? [])['size_code'] ?? ''), 2, '0', STR_PAD_LEFT) === $wantPlate];
            }
            if (!empty($a['corner_radius_mm'])) {
                $want = $a['corner_radius_mm'];
                $out[] = ['радиус', false, fn(array $it): bool => self::near($it['attrs']['corner_radius_mm'] ?? null, $want, 0.02)];
            }
            if (!empty($a['diameter_mm']) && !$q->insert_code) {
                $want = $a['diameter_mm'];
                $out[] = ['диаметр', false, fn(array $it): bool => self::near($it['attrs']['diameter_mm'] ?? null, $want, 0.15)];
            }
            if (!empty($a['pitch_mm'])) {
                $want = $a['pitch_mm'];
                $out[] = ['шаг', false, fn(array $it): bool => self::near($it['attrs']['pitch_mm'] ?? null, $want, 0.02)];
            }
            if (!empty($a['radius_mm'])) {
                $want = $a['radius_mm'];
                $out[] = ['радиус', false, fn(array $it): bool => self::near($it['attrs']['radius_mm'] ?? null, $want, 0.05)];
            }
            if (!empty($a['iso_group'])) {
                $want = strtoupper($a['iso_group']);
                $out[] = ['группа ISO', false, fn(array $it): bool => strtoupper((string)($it['attrs']['iso_group'] ?? '')) === $want
                    || str_contains(strtoupper((string)($it['attrs']['secondary_iso'] ?? '')), $want)];
            }
            if (!empty($a['operation'])) {
                $want = $a['operation'];
                $out[] = ['вид обработки', false, fn(array $it): bool => ($it['attrs']['operation'] ?? '') === $want];
            }
            if (!empty($a['grade'])) {
                $wantGrade = Normalize::compact((string)$a['grade']);
                $gradeRe = '/(?<![A-Za-z0-9])' . preg_quote($wantGrade, '/') . '(?![A-Za-z0-9])/iu';
                $out[] = ['марка', false, fn(array $it): bool => Normalize::compact((string)($it['attrs']['grade'] ?? '')) === $wantGrade
                    || preg_match($gradeRe, Normalize::homoglyphLatin((string)($it['name'] ?? ''))) === 1];
            }
        } elseif (in_array($fam, ['drill', 'mill', 'reamer'], true)) {
            if ($fam === 'mill' && $q->compat_insert) {
                $out[] = ['под пластину', true, fn(array $it): bool => self::millFits($it, $q)];
            }
            if (!empty($a['diameter_mm'])) {
                $want = $a['diameter_mm'];
                $tol = $want < 10 ? 0.06 : 0.11;
                $out[] = ['диаметр', true, fn(array $it): bool => self::near($it['attrs']['diameter_mm'] ?? null, $want, $tol)];
            }
            if (!empty($a['teeth'])) {
                $want = $a['teeth'];
                $out[] = ['зубья', false, fn(array $it): bool => self::intEq($it['attrs']['teeth'] ?? null, $want)];
            }
            if (!empty($a['shank_mm'])) {
                $want = $a['shank_mm'];
                $out[] = ['хвостовик', false, fn(array $it): bool => self::near($it['attrs']['shank_mm'] ?? null, $want, 0.5)];
            }
            if (!empty($a['radius_mm']) && $fam === 'mill') {
                $want = $a['radius_mm'];
                $out[] = ['радиус', false, fn(array $it): bool => self::near($it['attrs']['radius_mm'] ?? null, $want, 0.05)];
            }
            if (!empty($a['thickness_mm']) && $fam === 'mill') {
                $want = $a['thickness_mm'];
                $out[] = ['толщина', false, fn(array $it): bool => self::near($it['attrs']['thickness_mm'] ?? null, $want, 0.15)];
            }
            if (!empty($a['ld_ratio']) && $fam === 'drill') {
                $want = $a['ld_ratio'];
                $out[] = ['класс длины', false, fn(array $it): bool => self::intEq($it['attrs']['ld_ratio'] ?? null, $want)];
            }
            if (!empty($a['flutes2']) && $fam === 'mill') {
                $out[] = ['2 зуба', true, fn(array $it): bool => preg_match('/(?<![A-Z0-9])2\s*F(?![A-Z])|\bZ\s*=?\s*2(?!\d)|2\s*зуб/u', mb_strtoupper((string)($it['name'] ?? ''), 'UTF-8')) === 1];
            }
            if (!empty($a['angle_deg']) && $fam === 'drill') {
                $want = $a['angle_deg'];
                $out[] = ['угол при вершине', false, fn(array $it): bool => self::near($it['attrs']['angle_deg'] ?? null, $want, 1)];
            }
            if (!empty($a['angle_deg']) && $fam === 'countersink') {
                $want = $a['angle_deg'];
                $out[] = ['угол', true, fn(array $it): bool => self::near($it['attrs']['angle_deg'] ?? null, $want, 1)];
            }
        } elseif (in_array($fam, ['tap', 'die'], true)) {
            if ($q->thread) {
                $pitch = $a['pitch_mm'] ?? null;
                $out[] = ['резьба', true, fn(array $it): bool => self::threadMatch($it['attrs']['thread'] ?? null, $q->thread, $pitch)];
            }
            if (!empty($a['tap_kind'])) {
                $want = $a['tap_kind'];
                $out[] = ['исполнение', false, fn(array $it): bool => ($it['attrs']['tap_kind'] ?? '') === $want];
            }
        } elseif ($fam === 'holder') {
            if ($q->compat_insert || ($q->compat_shape && $q->compat_size)) {
                $out[] = ['под пластину', true, fn(array $it): bool => self::holderFits($it, $q)];
            }
            if ($q->holder_code) {
                $hc = $q->holder_code;
                $out[] = ['код', true, fn(array $it): bool => self::codeMatch($it, $hc)[0] > 0];
            }
            if (!empty($a['shank_mm'])) {
                $want = $a['shank_mm'];
                if (!empty($a['shank_section'])) {
                    $out[] = ['сечение', true, fn(array $it): bool => empty($it['attrs']['shank_diameter_mm'])
                        && self::near($it['attrs']['shank_mm'] ?? null, $want, 0.5)];
                } else {
                    $out[] = ['диаметр хвоста', true, fn(array $it): bool => self::near($it['attrs']['shank_diameter_mm'] ?? null, $want, 0.5)];
                }
            }
        } elseif ($fam === 'countersink') {
            if (!empty($a['diameter_mm'])) {
                $want = $a['diameter_mm'];
                $out[] = ['диаметр', true, fn(array $it): bool => self::near($it['attrs']['diameter_mm'] ?? null, $want, 0.2)];
            }
            if (!empty($a['angle_deg'])) {
                $want = $a['angle_deg'];
                $out[] = ['угол', false, fn(array $it): bool => self::near($it['attrs']['angle_deg'] ?? null, $want, 1)];
            }
        } elseif ($fam === 'saw') {
            if (!empty($a['diameter_mm'])) {
                $want = $a['diameter_mm'];
                $out[] = ['диаметр', true, fn(array $it): bool => self::near($it['attrs']['diameter_mm'] ?? null, $want, 0.5)];
            }
            if (!empty($a['teeth'])) {
                $want = $a['teeth'];
                $out[] = ['зубья', false, fn(array $it): bool => self::intEq($it['attrs']['teeth'] ?? null, $want)];
            }
        } elseif ($fam === 'accessory') {
            if (str_contains($q->low, 'патрон')) {
                $out[] = ['изделие', true, fn(array $it): bool => str_contains(Normalize::lower((string)($it['name'] ?? '')), 'патрон')
                    || str_contains(Normalize::lower((string)($it['name'] ?? '')), 'оправк')];
            }
            if (preg_match('/сверлильн/u', $q->low) === 1) {
                $out[] = ['сверлильный', true, fn(array $it): bool => str_contains(Normalize::lower((string)($it['name'] ?? '')), 'сверлильн')];
            }
            if (in_array('measuring', $q->category_hints, true)) {
                if (!empty($a['measure_code'])) {
                    $want = Normalize::compact($a['measure_code']);
                    $out[] = ['артикул', true, fn(array $it): bool => str_contains($it['_name_norm'] ?? '', $want)];
                }
                if (!empty($a['tolerance'])) {
                    $wantTol = strtoupper($a['tolerance']);
                    $out[] = ['допуск', true, fn(array $it): bool => str_contains(strtoupper(preg_replace('/\s+/u', '', Normalize::homoglyphLatin((string)($it['name'] ?? '')))), $wantTol)];
                }
                if (!empty($a['diameter_mm'])) {
                    $want = $a['diameter_mm'];
                    $out[] = ['диаметр', true, fn(array $it): bool => self::near(CatalogAttrs::gaugeDiameter((string)($it['name'] ?? '')), $want, 0.05)];
                }
            }
            if (!empty($a['taper'])) {
                $want = $a['taper'];
                $out[] = ['конус', true, fn(array $it): bool => (CatalogAttrs::accessoryMount((string)($it['name'] ?? ''))['taper'] ?? null) === $want];
            }
            if (!empty($a['weldon'])) {
                $out[] = ['хвостовик Weldon', true, fn(array $it): bool => preg_match('/WELDON|SLN|(?<![A-Z])SL(?=[\d-])/u', mb_strtoupper((string)($it['name'] ?? ''), 'UTF-8')) === 1];
            }
            if (!empty($a['tool_d_mm'])) {
                $want = $a['tool_d_mm'];
                $out[] = ['диаметр хвоста', true, fn(array $it): bool => self::near(CatalogAttrs::accessoryMount((string)($it['name'] ?? ''))['d'] ?? null, $want, 0.01)];
            }
            if (!empty($a['tool_l_mm'])) {
                $want = $a['tool_l_mm'];
                $out[] = ['длина', true, fn(array $it): bool => self::near(CatalogAttrs::accessoryMount((string)($it['name'] ?? ''))['l'] ?? null, $want, 0.01)];
            }
            if (!empty($a['chuck_system'])) {
                $want = Normalize::compact($a['chuck_system']);
                $out[] = ['система', false, fn(array $it): bool => str_contains($it['_name_norm'] ?? '', $want)];
            }
            if (!empty($a['chuck_taper'])) {
                $want = Normalize::compact($a['chuck_taper']);
                $out[] = ['конус патрона', true, fn(array $it): bool => str_contains($it['_name_norm'] ?? '', $want)];
            }
            if (!empty($a['self_tightening'])) {
                $out[] = ['самозажимной', true, fn(array $it): bool => str_contains(Normalize::lower((string)($it['name'] ?? '')), 'самозажимн')];
            }
            if (!empty($a['chuck_max_mm'])) {
                $want = $a['chuck_max_mm'];
                $out[] = ['диаметр зажима', true, fn(array $it): bool => CatalogAttrs::chuckCapacity((string)($it['name'] ?? '')) === $want];
            }
            if (!empty($a['clamp_set'])) {
                $out[] = ['прижимы', true, fn(array $it): bool => str_contains(Normalize::lower((string)($it['name'] ?? '')), 'прижим')];
            }
            if (!empty($a['slot_mm'])) {
                $want = $a['slot_mm'];
                $out[] = ['паз', true, fn(array $it): bool => CatalogAttrs::slotMmFromName((string)($it['name'] ?? '')) === $want];
            }
            if (!empty($a['collet_series'])) {
                $want = strtoupper($a['collet_series']);
                $out[] = ['серия', true, fn(array $it): bool => strtoupper((string)($it['attrs']['collet_series'] ?? '')) === $want];
            }
            if (!empty($a['jaw_series'])) {
                $wantSeries = Normalize::compact($a['jaw_series'] . '-' . $a['jaw_size']);
                $out[] = ['серия патрона', true, fn(array $it): bool => str_contains($it['_name_norm'] ?? '', $wantSeries)];
            }
            if (!empty($a['morse_from'])) {
                $pair = $a['morse_from'] . '/' . $a['morse_to'];
                $out[] = ['переход Морзе', true, fn(array $it): bool => str_contains((string)($it['name'] ?? ''), $pair)];
                if (!empty($a['with_tang'])) {
                    $out[] = ['с лапкой', false, fn(array $it): bool => str_contains((string)($it['name'] ?? ''), 'лапк')];
                }
            }
            if (!empty($a['bar_puller'])) {
                $out[] = ['барпуллер', true, fn(array $it): bool => str_contains(Normalize::lower((string)($it['name'] ?? '')), 'барпуллер')];
            }
            if (!empty($a['bar_shank_mm'])) {
                $side = 'S' . $a['bar_shank_mm'];
                $out[] = ['квадр. хвост', false, fn(array $it): bool => str_contains((string)($it['name'] ?? ''), $side) && str_contains((string)($it['name'] ?? ''), 'квадр')];
            }
            if (!empty($a['clamp_mm'])) {
                $want = $a['clamp_mm'];
                $wantStr = Normalize::gFormat((float)$want);
                $clampName = in_array('tool_holder', $q->category_hints, true) ? 'под хвостовик' : 'диаметр зажима';
                $clampRe = '/(?<![\d.])' . preg_quote($wantStr, '/') . '(?:[.,]0)?\s*мм/u';
                $out[] = [$clampName, false, fn(array $it): bool => self::near($it['attrs']['clamp_mm'] ?? null, $want, 0.5)
                    || (empty($it['attrs']['clamp_mm'])
                        && (str_ends_with((string)($it['attrs']['clamp_range'] ?? ''), '-' . $wantStr)
                            || preg_match($clampRe, (string)($it['name'] ?? '')) === 1))];
            }
            if (!empty($a['shank_mm'])) {
                $want = $a['shank_mm'];
                $out[] = ['хвостовик', false, fn(array $it): bool => self::near($it['attrs']['shank_mm'] ?? null, $want, 0.5)];
            }
        }

        if (!empty($a['coating'])) {
            $want = $a['coating'];
            $out[] = ['покрытие', false, fn(array $it): bool => self::sameText($it['attrs']['coating'] ?? null, $want)];
        }
        if (!empty($a['material'])) {
            $want = $a['material'];
            $out[] = ['материал', false, fn(array $it): bool => self::sameText($it['attrs']['material'] ?? null, $want)];
        }
        if (!empty($a['operation'])) {
            $want = $a['operation'];
            $out[] = ['обработка', false, fn(array $it): bool => ($it['attrs']['operation'] ?? '') === $want];
        }
        if (!empty($a['standard'])) {
            $want = Normalize::compact($a['standard']);
            $out[] = ['стандарт', false, fn(array $it): bool => str_contains(Normalize::compact((string)($it['attrs']['standard'] ?? '')), $want)];
        }
        if (!empty($a['hrc'])) {
            $want = $a['hrc'];
            $out[] = ['HRC', false, fn(array $it): bool => ($it['attrs']['hrc'] ?? 0) >= $want];
        }
        if ($q->brand) {
            $want = Normalize::compact($q->brand);
            $out[] = ['бренд', false, fn(array $it): bool => ($it['_brand_norm'] ?? '') === $want];
        }
        if ($q->category_hints) {
            $hints = $q->category_hints;
            $out[] = ['тип', true, fn(array $it): bool => in_array($it['category'] ?? '', $hints, true)];
        }
        return $out;
    }

    public static function roundShank(Query $q): bool
    {
        return $q->shank_round || in_array('holder_internal', $q->category_hints, true);
    }

    public static function holderFits(array $it, Query $q): bool
    {
        $info = $it['_insert_compat'] ?? null;
        if (!$info) {
            return false;
        }
        if (($info['shape'] ?? null) !== $q->compat_shape) {
            return false;
        }
        if ($q->compat_clearance && ($info['clearance'] ?? null) !== $q->compat_clearance) {
            return false;
        }
        if ($q->compat_size && ($info['size'] ?? null) !== $q->compat_size) {
            return false;
        }
        if ($q->compat_hand && !empty($info['hand']) && $info['hand'] !== $q->compat_hand) {
            return false;
        }
        return Compat::clampAcceptsHole($info['clamp'] ?? null, $q->compat_hole);
    }

    public static function insertFitsHolder(array $it, Query $q): bool
    {
        $info = $q->holder_compat ?? [];
        $attrs = $it['attrs'] ?? [];
        $src = !empty($attrs['iso_code']) ? $attrs['iso_code'] : ($it['sku'] ?? '');
        $code = strtoupper(Normalize::compact((string)$src));
        $m = [];
        if (preg_match('/^[A-Z]+/u', $code, $m) !== 1 || empty($info['size'])) {
            return false;
        }
        $pref = $m[0];
        $digits = mb_substr($code, mb_strlen($pref, 'UTF-8'), null, 'UTF-8');
        if ($pref[0] !== ($info['shape'] ?? null)) {
            return false;
        }
        if (!empty($info['clearance']) && mb_strlen($pref, 'UTF-8') > 1 && $pref[1] !== $info['clearance']) {
            return false;
        }
        $hole = mb_strlen($pref, 'UTF-8') >= 4 ? mb_substr($pref, 3, 1, 'UTF-8') : null;
        if (!Compat::clampAcceptsHole($info['clamp'] ?? null, $hole)) {
            return false;
        }
        return mb_substr($digits, 0, 2, 'UTF-8') === (string)$info['size'];
    }

    public static function millFits(array $it, Query $q): bool
    {
        $want = strtoupper($q->compat_insert ?? '');
        if ($want === '') {
            return false;
        }
        foreach ($it['_mill_inserts'] ?? [] as $code) {
            if (str_starts_with($code, $want) || str_starts_with($want, $code)) {
                return true;
            }
        }
        return false;
    }

    public static function intEq($value, $want): bool
    {
        if ($value === null || $want === null || !is_numeric($value) || !is_numeric($want)) {
            return false;
        }
        return (int)(float)$value === (int)(float)$want;
    }

    public static function near($value, $want, float $tol): bool
    {
        if ($value === null || $want === null || !is_numeric($value) || !is_numeric($want)) {
            return false;
        }
        return abs((float)$value - (float)$want) <= $tol + 1e-9;
    }

    public static function sameText($value, $want): bool
    {
        if (empty($value) || empty($want)) {
            return false;
        }
        $cv = Normalize::compact((string)$value);
        $cw = Normalize::compact((string)$want);
        return $cv === $cw || str_contains($cv, $cw);
    }

    public static function threadMatch($have, string $want, $pitch): bool
    {
        if (empty($have)) {
            return false;
        }
        $norm = static fn(string $s): string => preg_replace('/\s+/u', '', str_replace(['М', 'Х', '*'], ['M', 'X', 'X'], mb_strtoupper($s, 'UTF-8')));
        $h = $norm((string)$have);
        $w = $norm($want);
        if ($h === $w) {
            return true;
        }
        $mh = [];
        $mw = [];
        $okh = preg_match('/^M(\d+(?:\.\d+)?)/u', $h, $mh) === 1;
        $okw = preg_match('/^M(\d+(?:\.\d+)?)/u', $w, $mw) === 1;
        if ($okh && $okw && (float)$mh[1] === (float)$mw[1]) {
            if ($pitch === null) {
                return true;
            }
            $hp = [];
            return preg_match('/X(\d+(?:\.\d+)?)/u', $h, $hp) === 1 && abs((float)$hp[1] - (float)$pitch) < 0.01;
        }
        return Normalize::compact($h) === Normalize::compact($w);
    }

    // ---- основной поиск --------------------------------------------------------------------------
    public function search(string $text, int $limit = 8, bool $inStockOnly = true, ?array $pinNames = null): array
    {
        $q = new Query($text, $this->insertPrefixes);
        if ($q->insert_code) {
            $q->insert_code = $this->canonicalInsertCode($q->insert_code);
        }
        if ($q->compat_insert) {
            $fixed = $this->canonicalInsertCode($q->compat_insert);
            if ($fixed !== $q->compat_insert) {
                $q->setCompat($fixed);
            }
        }
        if ($pinNames) {
            $pinned = $this->searchPinned($q, $pinNames, $limit, $inStockOnly);
            if ($pinned) {
                return $pinned;
            }
        }
        if ($q->family === null) {
            if ($q->compat_insert) {
                return $this->searchCompat($q, $limit, $inStockOnly);
            }
            return $this->searchAmbiguous($q, $limit, $inStockOnly);
        }
        if ($q->compat_requested && !$q->compat_insert) {
            if (!($q->family === 'holder' && $q->compat_shape && $q->compat_size)) {
                return $this->compatAskCode($q);
            }
        }
        if ($q->holder_compat_requested && !$q->holder_compat) {
            return $this->holderAskCode($q);
        }
        return $this->searchFamily($q, $q->family, $limit, $inStockOnly);
    }

    private function compatAskCode(Query $q): array
    {
        return [
            'query' => $q->text, 'family' => $q->family, 'groups' => [], 'products' => [],
            'parsed' => $q->attrs, 'chips' => $this->chips($q, $q->family),
            'level' => 'уточните пластину', 'total_found' => 0, 'relaxations' => [],
            'follow_ups' => ['Укажите код пластины, под которую нужен инструмент (например CNMG 120408 или APMT1604).'],
            'note' => 'Для подбора совместимого инструмента нужен код пластины.',
        ];
    }

    private function holderAskCode(Query $q): array
    {
        return [
            'query' => $q->text, 'family' => 'insert', 'groups' => [], 'products' => [],
            'parsed' => $q->attrs, 'chips' => $this->chips($q, 'insert'),
            'level' => 'уточните державку', 'total_found' => 0, 'relaxations' => [],
            'follow_ups' => ['Укажите код державки, для которой нужна пластина (например MCLNR2525M12).'],
            'note' => 'Для подбора пластины нужен код державки.',
        ];
    }

    private function searchCompat(Query $q, int $limit, bool $inStockOnly): array
    {
        $groups = [];
        $products = [];
        $total = 0;
        foreach (['holder', 'mill'] as $fam) {
            if (empty($this->byFamily[$fam])) {
                continue;
            }
            $res = $this->searchFamily($q, $fam, $limit, $inStockOnly);
            if ($res['products']) {
                $groups[] = ['family' => $fam, 'title' => self::FAMILY_TITLES[$fam] ?? $fam,
                    'products' => $res['products'], 'total_found' => $res['total_found'], 'level' => $res['level']];
                foreach ($res['products'] as $p) {
                    $products[] = $p;
                }
                $total += $res['total_found'];
            }
        }
        $out = [
            'query' => $q->text, 'family' => null, 'groups' => $groups, 'products' => array_slice($products, 0, $limit),
            'parsed' => $q->attrs, 'chips' => $this->chips($q, null),
            'level' => $products ? 'подбор' : 'нет совместимых',
            'total_found' => $total, 'relaxations' => [],
            'follow_ups' => $products ? [] : ['Под пластину ' . $q->compat_insert . ' совместимых державок и корпусов фрез в каталоге не нашлось.'],
            'note' => 'Показан инструмент, совместимый с пластиной ' . $q->compat_insert . '.',
        ];
        if ($q->compat_insert) {
            $out['compatible_insert'] = $q->compat_insert;
        }
        return $out;
    }

    private function searchAmbiguous(Query $q, int $limit, bool $inStockOnly): array
    {
        if (!$q->free_tokens && !$q->insert_code && !$q->holder_code && !$q->attrs && !$q->compat_insert) {
            return [
                'query' => $q->text, 'family' => null, 'groups' => [], 'products' => [],
                'parsed' => [], 'chips' => [], 'level' => 'уточните группу',
                'total_found' => 0, 'relaxations' => [],
                'follow_ups' => ['Укажите группу товара и параметры: например «сверло 8,5 мм» или «CNMG 120408».'],
            ];
        }
        $groups = [];
        foreach (['insert', 'drill', 'mill', 'tap', 'holder', 'reamer', 'countersink', 'accessory'] as $fam) {
            if (empty($this->byFamily[$fam])) {
                continue;
            }
            $res = $this->searchFamily($q, $fam, 3, $inStockOnly);
            if ($res['products']) {
                $groups[] = ['family' => $fam, 'title' => self::FAMILY_TITLES[$fam] ?? $fam, 'products' => $res['products'],
                    'total_found' => $res['total_found'], 'level' => $res['level']];
            }
        }
        usort($groups, static fn($x, $y) => $y['total_found'] <=> $x['total_found']);
        $products = [];
        foreach ($groups as $g) {
            foreach ($g['products'] as $p) {
                $products[] = $p;
            }
        }
        $products = array_slice($products, 0, $limit);
        $top = array_slice($groups, 0, 4);
        $sum = 0;
        foreach ($top as $g) {
            $sum += $g['total_found'];
        }
        return [
            'query' => $q->text, 'family' => null, 'groups' => $top, 'products' => $products,
            'parsed' => $q->attrs, 'chips' => $this->chips($q, null), 'level' => 'уточните группу',
            'total_found' => $sum, 'relaxations' => [],
            'follow_ups' => ['Уточните группу товара: пластина, сверло, фреза, метчик, державка.'],
            'note' => 'Запрос без явной группы — показаны лучшие совпадения по разным группам.',
        ];
    }

    public static function pinnedMatch($value, string $want): bool
    {
        $v = Normalize::compact((string)($value ?? ''));
        $w = Normalize::compact($want);
        if ($v === '' || $w === '') {
            return false;
        }
        if ($v === $w) {
            return true;
        }
        $after = mb_substr($v, mb_strlen($w, 'UTF-8'), 1, 'UTF-8');
        return str_starts_with($v, $w) && !ctype_digit($after);
    }

    private function searchPinned(Query $q, array $names, int $limit, bool $inStockOnly): ?array
    {
        $pool = [];
        $seen = [];
        foreach ($this->byFamily as $famPool) {
            foreach ($famPool as $it) {
                $key = !empty($it['id']) ? $it['id'] : $it['_uid'];
                if (isset($seen[$key])) {
                    continue;
                }
                $match = false;
                foreach ($names as $n) {
                    if (self::pinnedMatch($it['name'] ?? '', $n) || self::pinnedMatch($it['sku'] ?? '', $n)) {
                        $match = true;
                        break;
                    }
                }
                if ($match) {
                    $pool[] = $it;
                    $seen[$key] = true;
                }
            }
        }
        if (!$pool) {
            return null;
        }
        $results = $this->collect($pool, $q, [], [], false, $q->family ?? '');
        $withStock = [];
        $without = [];
        foreach ($results as $r) {
            if (($r[0]['stock'] ?? 0) > 0) {
                $withStock[] = $r;
            } else {
                $without[] = $r;
            }
        }
        $results = array_merge($withStock, $without);
        $availability = '';
        if ($inStockOnly && $results && !$withStock) {
            $availability = 'нет в наличии — показаны позиции под заказ';
        } elseif ($inStockOnly && $without) {
            $availability = 'часть позиций под заказ';
        }
        $fam = $q->family ?: ($pool[0]['family'] ?? null);
        $cards = [];
        foreach ($results as [$it, $score]) {
            $cards[] = $this->card($it, $score, $q);
        }
        $extra = $q->family ? $this->searchFamily($q, $q->family, $limit, $inStockOnly)
            : $this->searchAmbiguous($q, $limit, $inStockOnly);
        $have = [];
        foreach ($cards as $p) {
            $have[Normalize::compact((string)($p['sku'] ?? '')) . Normalize::compact((string)($p['name'] ?? ''))] = true;
        }
        $added = [];
        foreach ($extra['products'] ?? [] as $p) {
            $key = Normalize::compact((string)($p['sku'] ?? '')) . Normalize::compact((string)($p['name'] ?? ''));
            if (isset($have[$key])) {
                continue;
            }
            $have[$key] = true;
            $added[] = $p;
        }
        $cards = array_slice(array_merge($cards, $added), 0, $limit);
        $out = [
            'query' => $q->text, 'family' => $fam, 'groups' => [], 'products' => $cards,
            'parsed' => $q->attrs, 'chips' => $this->chips($q, $fam), 'level' => 'точное',
            'total_found' => count($results) + count($added), 'relaxations' => [], 'follow_ups' => [],
            'category_hints' => $q->category_hints, 'trained' => true,
        ];
        if ($availability !== '') {
            $out['availability'] = $availability;
        }
        return $out;
    }

    private function searchFamily(Query $q, string $fam, int $limit, bool $inStockOnly): array
    {
        $pool = $this->byFamily[$fam] ?? [];
        if (!$pool) {
            $pool = $this->relatedPool($fam);
        }
        // S5: сужаем пул через инвертированный индекс токенов (OR семантика — достаточно одного совпадения)
        $pool = $this->narrowPool($pool, $q->free_tokens);
        $filters = $this->filters($q, $fam);
        $hard = [];
        $soft = [];
        foreach ($filters as [$n, $isHard, $f]) {
            if ($isHard) {
                $hard[] = [$n, $f];
            } else {
                $soft[] = [$n, $f];
            }
        }
        $relaxed = [];
        $availability = '';
        // B9: порог общего запроса — группа есть, но нет кода/параметров/категории → уточнить
        if (empty($filters) && !$q->insert_code && !$q->holder_code) {
            return [
                'query' => $q->text, 'family' => $fam, 'groups' => [], 'products' => [],
                'parsed' => $q->attrs, 'chips' => $this->chips($q, $fam), 'level' => 'уточните группу',
                'total_found' => 0, 'relaxations' => [],
                'follow_ups' => ['Укажите параметры: диаметр, код, марку или тип инструмента.'],
                'category_hints' => $q->category_hints,
            ];
        }
        $results = $this->collect($pool, $q, $hard, $soft, $inStockOnly, $fam);
        if (!$results && $inStockOnly && $filters) {
            $results = $this->collect($pool, $q, $hard, $soft, false, $fam);
            if ($results) {
                $availability = 'нет в наличии — показаны позиции под заказ';
            }
        }
        $nearest = [];
        if (!$results && $fam === 'mill' && $q->compat_insert && !empty($q->attrs['diameter_mm'])) {
            $guard = [];
            foreach ($hard as [$n, $f]) {
                if ($n !== 'диаметр') {
                    $guard[] = $f;
                }
            }
            foreach ($soft as [$n, $f]) {
                $guard[] = $f;
            }
            $nearest = $this->nearestDiameter($pool, $q->attrs['diameter_mm'], $fam, $q, $limit, $guard);
            if ($nearest) {
                $relaxed[] = 'точного диаметра нет — показан ближайший к ' . Normalize::fmtNum($q->attrs['diameter_mm']) . ' мм';
                $results = $nearest;
            }
        }
        if (!$results) {
            $activeSoft = $soft;
            $activeHard = $hard;
            $steps = count($soft) + count($hard);
            for ($i = 0; $i < $steps; $i++) {
                if ($activeSoft) {
                    $popped = array_pop($activeSoft);
                    $relaxed[] = 'ослаблен фильтр «' . $popped[0] . '»';
                } elseif ($activeHard && count($activeHard) > 1) {
                    $popped = array_pop($activeHard);
                    $relaxed[] = 'ослаблен фильтр «' . $popped[0] . '»';
                } else {
                    break;
                }
                $results = $this->collect($pool, $q, $activeHard, $activeSoft, $inStockOnly, $fam);
                if (!$results && $inStockOnly) {
                    $results = $this->collect($pool, $q, $activeHard, $activeSoft, false, $fam);
                    if ($results) {
                        $availability = 'нет в наличии — показаны позиции под заказ';
                    }
                }
                if ($results) {
                    break;
                }
            }
        }
        // B3: fuzzy цифровой хвост кода при нулевом точном совпадении
        if (!$results && ($q->insert_code || $q->holder_code) && in_array($fam, ['insert', 'holder'], true)) {
            $wantCode = $q->insert_code ?: ($q->holder_code ?? '');
            $fuzzy = $this->fuzzyCodeSearch($wantCode, $fam, $limit, $inStockOnly);
            if ($fuzzy) {
                $relaxed[] = 'возможная опечатка в коде — показан ближайший аналог';
                $results = $fuzzy;
                $nearest = true; // уровень 'аналог'
            }
        }
        $codeLevel = 0;
        if ($q->insert_code || $q->holder_code) {
            $wantCode = $q->insert_code ?: ($q->holder_code ?? '');
            foreach ($results as [$it, $score]) {
                $lvl = self::codeMatch($it, $wantCode)[0];
                if ($lvl > $codeLevel) {
                    $codeLevel = $lvl;
                }
            }
        }
        if (!$results && in_array($fam, ['drill', 'mill', 'reamer', 'countersink', 'saw'], true) && !empty($q->attrs['diameter_mm'])) {
            $nearest = $this->nearestDiameter($pool, $q->attrs['diameter_mm'], $fam, $q, $limit);
            if ($nearest) {
                $relaxed[] = 'точного диаметра нет — показаны ближайшие к ' . Normalize::fmtNum($q->attrs['diameter_mm']) . ' мм';
                $results = $nearest;
            }
        }
        $level = 'точное';
        if ($nearest) {
            $level = 'аналог';
        } elseif ($relaxed || ($codeLevel > 0 && $codeLevel < 3)) {
            $level = 'частичное';
        }
        if (!empty($q->attrs['tap_drill_for'])) {
            $relaxed[] = 'под резьбу ' . $q->attrs['tap_drill_for'] . ' диаметр сверла ' . Normalize::fmtNum($q->attrs['diameter_mm'] ?? null) . ' мм';
        }
        $products = [];
        foreach (array_slice($results, 0, $limit) as [$it, $score]) {
            $products[] = $this->card($it, $score, $q);
        }
        $tapDrill = $fam === 'drill' ? Compat::tapDrillFor($q->thread) : null;
        $follow = $this->followUps($q, $fam, $products);
        $out = [
            'query' => $q->text, 'family' => $fam, 'groups' => [], 'products' => $products,
            'parsed' => $q->attrs, 'chips' => $this->chips($q, $fam), 'level' => $level,
            'total_found' => count($results), 'relaxations' => $relaxed, 'follow_ups' => $follow,
            'category_hints' => $q->category_hints,
        ];
        if ($availability !== '') {
            $out['availability'] = $availability;
        }
        if ($tapDrill) {
            $out['tap_drill'] = $tapDrill;
        }
        if ($fam === 'holder' && $q->holder_code) {
            $hint = Compat::holderInsertHint($q->holder_code);
            if ($hint) {
                $out['fits_insert'] = $hint;
            }
        }
        if ($q->family === 'insert' && $q->insert_code) {
            $out['insert_code'] = $q->insert_code;
        }
        if ($q->family === 'holder' && $q->holder_code) {
            $out['holder_code'] = $q->holder_code;
        }
        if ($q->compat_insert) {
            $out['compatible_insert'] = $q->compat_insert;
        }
        if ($q->holder_compat && $fam === 'insert') {
            $out['fits_holder'] = $q->holder_compat_code;
        }
        return $out;
    }

    private function relatedPool(string $fam): array
    {
        if ($fam === 'tap') {
            return $this->byFamily['die'] ?? [];
        }
        if ($fam === 'die') {
            return $this->byFamily['tap'] ?? [];
        }
        if ($fam === 'saw') {
            $out = [];
            foreach ($this->byFamily['mill'] ?? [] as $it) {
                if (($it['category'] ?? '') === 'saw_blade') {
                    $out[] = $it;
                }
            }
            return $out;
        }
        return [];
    }

    /** Сужение пула через инвертированный индекс (OR: достаточно одного совпадения токена). */
    private function narrowPool(array $pool, array $tokens): array
    {
        if (empty($tokens)) {
            return $pool;
        }
        $matchingUids = [];
        foreach ($tokens as $t) {
            foreach ($this->byToken[$t] ?? [] as $uid) {
                $matchingUids[(int)$uid] = true;
            }
        }
        if (empty($matchingUids)) {
            return [];
        }
        $out = [];
        foreach ($pool as $it) {
            if (isset($matchingUids[$it['_uid'] ?? -1])) {
                $out[] = $it;
            }
        }
        return $out;
    }

    /** @return list<array{0:array<string,mixed>,1:float}> */
    private function collect(array $pool, Query $q, array $hard, array $soft, bool $inStockOnly, string $fam): array
    {
        $out = [];
        $tokens = $q->free_tokens;
        // S4: метаданные токенов считаем один раз на запрос
        $correctable = [];
        foreach ($tokens as $t) {
            if (mb_strlen($t, 'UTF-8') >= 5 && preg_match('/\d/u', $t) === 1) {
                $correctable[$t] = true;
            }
        }
        $hasExactCode = false;
        foreach ($pool as $it) {
            $stock = $it['stock'] ?? 0;
            if ($inStockOnly && $stock <= 0) {
                continue;
            }
            if (!($it['active'] ?? true) && $stock <= 0) {
                continue;
            }
            $ok = true;
            foreach ($hard as [$n, $f]) {
                if (!$f($it)) {
                    $ok = false;
                    break;
                }
            }
            if (!$ok) {
                continue;
            }
            foreach ($soft as [$n, $f]) {
                if (!$f($it)) {
                    $ok = false;
                    break;
                }
            }
            if (!$ok) {
                continue;
            }
            $textScore = $this->textScore($it, $tokens, $correctable);
            $codeLvl = 0;
            if ($q->insert_code || $q->holder_code) {
                $codeLvl = self::codeMatch($it, $q->insert_code ?: ($q->holder_code ?? ''))[0];
            }
            $score = 0.0;
            if ($codeLvl === 3) {
                $score += 120;
                $hasExactCode = true;
            } elseif ($codeLvl === 2) {
                $score += 95;
            } elseif ($codeLvl === 1) {
                $score += 80;
            } elseif ($hard) {
                $score += 60;
            } else {
                $score += 40;
            }
            $score += 3.0 * $textScore;
            if ($tokens) {
                $doc = $it['_tokens'] ?? [];
                $hits = 0;
                foreach ($tokens as $t) {
                    if (isset($doc[$t])) {
                        $hits++;
                    }
                }
                $score += 4.0 * $hits;
            }
            if ($stock > 0) {
                $score += 5;
            }
            if (empty($it['price_on_request'])) {
                $score += 2;
            }
            if ($it['active'] ?? true) {
                $score += 1;
            }
            $score += min($stock, 200) / 200.0;
            $out[] = [$it, $score];
        }
        usort($out, static fn($x, $y) => ($y[1] <=> $x[1]) ?: (($y[0]['stock'] ?? 0) <=> ($x[0]['stock'] ?? 0)));
        $seen = [];
        $uniq = [];
        foreach ($out as [$it, $score]) {
            $key = ($it['_brand_norm'] ?? '') . '|' . Normalize::compact((string)(!empty($it['sku']) ? $it['sku'] : ($it['name'] ?? '')));
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $uniq[] = [$it, $score];
        }
        $rankCount = count(self::$brandRank);
        if ($hasExactCode) {
            // точный код: бренд → остаток → score
            usort($uniq, static function ($x, $y) use ($rankCount) {
                $bx = self::$brandRank[$x[0]['_brand_norm'] ?? ''] ?? $rankCount;
                $by = self::$brandRank[$y[0]['_brand_norm'] ?? ''] ?? $rankCount;
                return ($bx <=> $by) ?: (($y[0]['stock'] ?? 0) <=> ($x[0]['stock'] ?? 0)) ?: ($y[1] <=> $x[1]);
            });
        } else {
            // свободный запрос: score → бренд → остаток (BM25-стиль)
            usort($uniq, static function ($x, $y) use ($rankCount) {
                $bx = self::$brandRank[$x[0]['_brand_norm'] ?? ''] ?? $rankCount;
                $by = self::$brandRank[$y[0]['_brand_norm'] ?? ''] ?? $rankCount;
                return ($y[1] <=> $x[1]) ?: ($bx <=> $by) ?: (($y[0]['stock'] ?? 0) <=> ($x[0]['stock'] ?? 0));
            });
        }
        return $uniq;
    }

    /** @return list<array{0:array<string,mixed>,1:float}> */
    private function nearestDiameter(array $pool, float $want, string $fam, Query $q, int $limit, ?array $guard = null): array
    {
        $cands = [];
        foreach ($pool as $it) {
            $d = ($it['attrs'] ?? [])['diameter_mm'] ?? null;
            if ($d === null) {
                continue;
            }
            if (($it['stock'] ?? 0) <= 0) {
                continue;
            }
            if ($guard) {
                $ok = true;
                foreach ($guard as $f) {
                    if (!$f($it)) {
                        $ok = false;
                        break;
                    }
                }
                if (!$ok) {
                    continue;
                }
            }
            $cands[] = [abs((float)$d - $want), $it];
        }
        if (!$cands) {
            return [];
        }
        usort($cands, static fn($x, $y) => ($x[0] <=> $y[0]) ?: (($y[1]['stock'] ?? 0) <=> ($x[1]['stock'] ?? 0)));
        $bestDiff = $cands[0][0];
        $out = [];
        foreach ($cands as [$diff, $it]) {
            if ($diff <= $bestDiff + 1e-9) {
                $out[] = [$it, 30 - $diff];
            }
        }
        return array_slice($out, 0, $limit);
    }

    // B3: fuzzy поиск по цифровому хвосту кода (Дамерау ≤1) в префиксе каталога
    private function fuzzyCodeSearch(string $wantCode, string $fam, int $limit, bool $inStockOnly): array
    {
        $compact = Normalize::compact($wantCode);
        if (mb_strlen($compact, 'UTF-8') < 4) {
            return [];
        }
        $pref = mb_substr($compact, 0, 4, 'UTF-8');
        $tail = mb_substr($compact, 4, null, 'UTF-8');
        if ($tail === '') {
            return [];
        }
        $cands = [];
        foreach ($this->byPrefix[$pref] ?? [] as $uid) {
            $it = $this->items[$uid] ?? null;
            if (!$it) {
                continue;
            }
            if ($inStockOnly && (($it['stock'] ?? 0) <= 0)) {
                continue;
            }
            $attrs = $it['attrs'] ?? [];
            $iso = Normalize::compact((string)($attrs['iso_code'] ?? ''));
            $holder = Normalize::compact((string)($attrs['holder_code'] ?? ''));
            $sku = Normalize::compact((string)($it['sku'] ?? ''));
            $bestDist = null;
            foreach ([$iso, $holder, $sku] as $code) {
                if ($code === '' || $code === $compact) {
                    continue;
                }
                $codePref = mb_substr($code, 0, 4, 'UTF-8');
                if ($codePref !== $pref) {
                    continue;
                }
                $codeTail = mb_substr($code, 4, null, 'UTF-8');
                $dist = Normalize::damerau($tail, $codeTail, 1);
                if ($dist <= 1 && ($bestDist === null || $dist < $bestDist)) {
                    $bestDist = $dist;
                }
            }
            if ($bestDist !== null) {
                $cands[] = [$bestDist, $it];
            }
        }
        if (empty($cands)) {
            return [];
        }
        usort($cands, static fn($x, $y) => ($x[0] <=> $y[0]) ?: (($y[1]['stock'] ?? 0) <=> ($x[1]['stock'] ?? 0)));
        $out = [];
        foreach (array_slice($cands, 0, $limit) as [$dist, $it]) {
            $out[] = [$it, 50 - $dist * 10];
        }
        return $out;
    }

    // ---- карточка и подсказки --------------------------------------------------------------------
    private function card(array $it, float $score, Query $q): array
    {
        $attrs = $it['attrs'] ?? [];
        $price = (float)($it['price'] ?? 0.0);
        $por = (bool)($it['price_on_request'] ?? false);
        $url = (string)($it['url'] ?? '');
        $currency = (string)($it['currency'] ?? 'RUB');
        $filtered = [];
        foreach ($attrs as $k => $v) {
            if ($v !== null && $v !== '' && $v !== []) {
                $filtered[$k] = $v;
            }
        }
        return [
            'sku' => $it['sku'] ?? '',
            'code_1c' => $it['id'] ?? '',
            'name' => $it['name'] ?? '',
            'brand' => $it['brand'] ?? '',
            'category' => $it['category'] ?? '',
            'family' => $it['family'] ?? '',
            'grade' => $attrs['grade'] ?? '',
            'iso_group' => $attrs['iso_group'] ?? '',
            'stock' => $it['stock'] ?? 0,
            'price' => $price,
            'currency' => $currency,
            'price_on_request' => $por,
            'price_display' => Rates::priceDisplay($price, $currency, $por),
            'source_site' => 'qtool.ru',
            'qtool_url' => $url,
            'shop_links_markdown' => $url !== '' ? '[Открыть на qtool.ru](' . $url . ')' : '',
            'attrs' => $filtered,
            'score' => round($score, 2),
        ];
    }

    private function chips(Query $q, ?string $fam): array
    {
        $chips = [];
        if ($fam) {
            $chips[] = 'группа: ' . (self::FAMILY_TITLES[$fam] ?? $fam);
        }
        foreach ($q->category_hints as $cat) {
            $title = Query::CATEGORY_TITLES[$cat] ?? null;
            if ($title) {
                $chips[] = 'тип: ' . $title;
            }
        }
        $a = $q->attrs;
        if ($q->insert_code) {
            if (!empty($a['insert_prefix'])) {
                $chips[] = trim('пластина: ' . $a['insert_prefix'] . ' ' . ($a['size_code'] ?? ''));
            } else {
                $chips[] = 'код: ' . $q->insert_code;
            }
        }
        if ($q->holder_code && !($fam === 'insert' && $q->holder_compat_code)) {
            $chips[] = 'код: ' . $q->holder_code;
        }
        if ($q->compat_insert) {
            $chips[] = 'под пластину: ' . $q->compat_insert;
        }
        if ($q->holder_compat && $fam === 'insert') {
            $chips[] = 'под державку: ' . $q->holder_compat_code;
        }
        if (!empty($a['plate_shape'])) {
            $chips[] = 'форма: ' . (Codes::PLATE_SHAPE_TITLES[$a['plate_shape']] ?? $a['plate_shape']);
        }
        if (!empty($a['plate_size'])) {
            $chips[] = 'размер: ' . $a['plate_size'];
        }
        if (!empty($a['hand']) && $fam === 'holder') {
            $chips[] = $a['hand'] === 'R' ? 'державка: правая' : 'державка: левая';
        }
        if (!empty($a['diameter_mm']) && (!$q->thread || !empty($a['tap_drill_for']))) {
            $chips[] = 'диаметр: ' . Normalize::fmtNum($a['diameter_mm']) . ' мм';
        }
        if ($q->thread) {
            $chips[] = 'резьба: ' . $q->thread;
        }
        if (!empty($a['teeth'])) {
            $chips[] = 'зубьев: ' . $a['teeth'];
        }
        if (!empty($a['ld_ratio'])) {
            $chips[] = 'длина: ' . $a['ld_ratio'] . 'D';
        }
        if (!empty($a['angle_deg'])) {
            $chips[] = 'угол: ' . Normalize::fmtNum($a['angle_deg']) . '°';
        }
        if (!empty($a['shank_section'])) {
            $sec = (string)$a['shank_section'];
            if (!str_contains($sec, '×')) {
                $sec = mb_substr($sec, 0, 2, 'UTF-8') . '×' . mb_substr($sec, 2, null, 'UTF-8');
            }
            $chips[] = 'сечение: ' . $sec . ' мм';
        } elseif (!empty($a['shank_mm'])) {
            if (self::roundShank($q)) {
                $chips[] = 'хвост: Ø' . Normalize::fmtNum($a['shank_mm']) . ' мм';
            } else {
                $chips[] = 'хвостовик: ' . Normalize::fmtNum($a['shank_mm']) . ' мм';
            }
        }
        if (!empty($a['iso_group'])) {
            $chips[] = 'группа ISO: ' . $a['iso_group'];
        }
        if (!empty($a['operation'])) {
            $opMap = ['finishing' => 'чистовая', 'semi_finishing' => 'получистовая', 'roughing' => 'черновая'];
            $chips[] = 'обработка: ' . ($opMap[$a['operation']] ?? $a['operation']);
        }
        if (!empty($a['grade'])) {
            $chips[] = 'марка: ' . $a['grade'];
        }
        if (!empty($a['collet_series'])) {
            $chips[] = 'серия: ' . $a['collet_series'];
        }
        if (!empty($a['jaw_series'])) {
            $chips[] = 'серия патрона: ' . $a['jaw_series'] . '-' . $a['jaw_size'];
        }
        if (!empty($a['morse_from'])) {
            $chips[] = 'переход: Морзе ' . $a['morse_from'] . ' → Морзе ' . $a['morse_to'];
        }
        if (!empty($a['with_tang'])) {
            $chips[] = 'с лапкой';
        }
        if (!empty($a['bar_shank_mm'])) {
            $side = Normalize::fmtNum($a['bar_shank_mm']);
            $chips[] = 'квадрат: ' . $side . '×' . $side . ' мм';
        }
        if (!empty($a['clamp_mm'])) {
            if (in_array('tool_holder', $q->category_hints, true)) {
                $chips[] = 'под хвостовик: ' . Normalize::fmtNum($a['clamp_mm']) . ' мм';
            } else {
                $chips[] = 'под диаметр: ' . Normalize::fmtNum($a['clamp_mm']) . ' мм';
            }
        }
        if (!empty($a['thickness_mm'])) {
            $chips[] = 'толщина: ' . Normalize::fmtNum($a['thickness_mm']) . ' мм';
        }
        if (!empty($a['coating'])) {
            $chips[] = 'покрытие: ' . $a['coating'];
        }
        if (!empty($a['material'])) {
            $chips[] = 'материал: ' . $a['material'];
        }
        if (!empty($a['standard'])) {
            $chips[] = 'стандарт: ' . $a['standard'];
        }
        if (!empty($a['radius_mm'])) {
            $chips[] = 'радиус: ' . Normalize::fmtNum($a['radius_mm']) . ' мм';
        }
        if (!empty($a['corner_radius_mm'])) {
            $chips[] = 'радиус: ' . Normalize::fmtNum($a['corner_radius_mm']) . ' мм';
        }
        if (!empty($a['taper'])) {
            $chips[] = 'конус: ' . $a['taper'];
        }
        if (!empty($a['weldon'])) {
            $chips[] = 'хвостовик: Weldon';
        }
        if (!empty($a['tool_d_mm'])) {
            $chips[] = 'диаметр хвоста: ' . Normalize::fmtNum($a['tool_d_mm']) . ' мм';
        }
        if (!empty($a['tool_l_mm'])) {
            $chips[] = 'длина: ' . Normalize::fmtNum($a['tool_l_mm']) . ' мм';
        }
        if (!empty($a['chuck_system'])) {
            $chips[] = 'система: ' . $a['chuck_system'];
        }
        if (!empty($a['chuck_taper'])) {
            $chips[] = 'конус патрона: ' . $a['chuck_taper'];
        }
        if (!empty($a['slot_mm'])) {
            $chips[] = 'паз: ' . $a['slot_mm'] . ' мм';
        }
        return $chips;
    }

    private function followUps(Query $q, string $fam, array $products): array
    {
        $a = $q->attrs;
        $tips = [];
        if ($q->compat_requested && !$q->compat_insert && !(!empty($a['plate_shape']) && !empty($a['plate_size']))) {
            $tips[] = 'Укажите код пластины, под которую нужен инструмент (например CNMG 120408 или APMT1604).';
        }
        if ($fam === 'drill') {
            if (empty($a['diameter_mm'])) {
                $tips[] = 'Укажите диаметр сверла (например «8,5 мм»).';
            }
            if (empty($a['material'])) {
                $tips[] = 'Уточните материал: HSS, HSS-E (нержавейка) или твердый сплав.';
            }
        } elseif ($fam === 'mill') {
            if (empty($a['diameter_mm'])) {
                $tips[] = 'Укажите диаметр фрезы.';
            }
            if (empty($a['teeth'])) {
                $tips[] = 'Уточните число зубьев (2F, 3F, 4F).';
            }
        } elseif (in_array($fam, ['tap', 'die'], true)) {
            if (!$q->thread) {
                $tips[] = 'Укажите резьбу: например М10х1,5.';
            }
        } elseif ($fam === 'holder') {
            if (!$q->holder_code && empty($a['shank_mm'])) {
                if (self::roundShank($q)) {
                    $tips[] = 'Укажите диаметр хвоста (16, 20, 25 мм) или код державки.';
                } else {
                    $tips[] = 'Укажите сечение державки (16х16, 20х20, 25х25) или её код.';
                }
            }
        } elseif ($fam === 'insert') {
            if (!$q->insert_code && !$q->holder_compat && !(!empty($a['plate_shape']) || !empty($a['plate_size']))) {
                $tips[] = 'Укажите код пластины (например CNMG 120408) или форму и размер.';
            }
        } elseif ($fam === 'accessory') {
            if (in_array('tool_holder', $q->category_hints, true) && empty($a['clamp_mm'])) {
                $tips[] = 'Укажите диаметр хвостовика инструмента (16, 20, 25, 32 мм).';
            }
        }
        return array_slice($tips, 0, 3);
    }
}