<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Разбор намерения запроса: группа, категория, коды, атрибуты, совместимость.
 * Порт class Query из src/catalog_search.py.
 */
final class Query
{
    public string $text;
    public string $low;
    public array $variants;
    public string $compact;
    public ?string $family = null;
    public array $category_hints = [];
    public array $attrs = [];
    public ?string $code = null;
    public ?string $insert_code = null;
    public ?string $holder_code = null;
    public ?string $thread = null;
    public ?string $brand = null;
    public array $free_tokens = [];
    public ?string $compat_insert = null;
    public ?string $compat_prefix = null;
    public ?string $compat_shape = null;
    public ?string $compat_clearance = null;
    public ?string $compat_hole = null;
    public ?string $compat_size = null;
    public ?string $compat_hand = null;
    public bool $compat_requested = false;
    public ?array $holder_compat = null;
    public ?string $holder_compat_code = null;
    public bool $holder_compat_requested = false;
    public bool $shank_round = false;
    /** @var array<string,true> */
    private array $insert_prefixes;

    public const FAMILY_KEYWORDS = [
        ['insert', 'пластин|insert|cnmg|wnmg|tcmt|tcgt|ccmt|ccgt|dcmt|vcgt|apmt|apkt|wcmt|spmg|sekt|lnmu|16er|16ir|22er|22ir|mgmn|mrgn|8gr|6gr|3gr|zqmx'],
        ['drill', 'сверл|сверло|drill|коронк|центровк'],
        ['mill', 'фрез|mill|борфрез'],
        ['tap', 'метчик|\btap\b|раскатник'],
        ['die', 'плашк|\bdies?\b'],
        ['reamer', 'разверт'],
        ['countersink', 'зенков|зенкер|фаскосним|гратосним'],
        ['holder', 'державк|борштанг|holder|резец|резц|минирез|оправк|расточн'],
        ['accessory', 'цанг|патрон|винт|гайк|ключ|сож|тиск|кулачк|адаптер|переходник|втулк|держател|барпул'],
        ['measuring', 'штанген|микрометр|нутромер|линейк|угломер|индикатор|рулетк'],
        ['saw', 'пил[аы]|пильн|дисков.*пил'],
    ];

    public const CATEGORY_HINTS = [
        'drill' => [
            ['center_drill', 'центровоч|центровк'],
            ['crown_drill', 'корончат'],
            ['drill_head', '(?<!под )головк'],
            ['indexable_drill_body', 'корпусн|сменн.*пластин|под пластину|под головк|сверл\w*[^,.]*пластин'],
            ['solid_carbide_drill', 'твердосплав|vhm'],
            ['hss_drill', 'hss|р6м5|p6m5|к\/х'],
        ],
        'mill' => [
            ['ball_mill', 'сферич|шарова|ball'],
            ['radius_mill', 'радиусн|с радиусом'],
            ['thread_mill', 'резьбофрез'],
            ['face_mill', 'торцев|насадн|со сменными пластин|корпусн'],
            ['slot_mill', 'дисков|пазов|т-образн|отрезн'],
            ['burr', 'борфрез'],
            ['end_mill', 'концев|end'],
        ],
        'tap' => [
            ['forming_tap', 'раскатн'],
            ['pipe_tap', 'трубн|\bG\d'],
            ['machine_tap', 'машинн|метрич|сквозн|гаечн'],
        ],
        'holder' => [
            ['holder_internal', 'расточн|борштанг|внутренн'],
            ['holder_grooving', 'канавочн|канавк|отрезн'],
            ['holder_threading', 'резьбов'],
            ['holder_external', 'наружн|проходн|подрезн'],
        ],
        'accessory' => [
            ['tool_holder', 'осев[а-яё]*\s+инструмент|токарн[а-яё]*\s+блок'],
            ['machine_jaw', 'кулачк(?:а|и|ов|ам|ами|ах|у|ом)\b'],
            ['collet', 'цанг(?:а|и|у|ой|ам|ами|ах)\b'],
            ['machine_vice', 'тиск(?:и|ов|ам|ами|ах|)\b'],
        ],
    ];

    public const CATEGORY_TITLES = [
        'holder_internal' => 'расточная', 'holder_external' => 'наружная',
        'holder_grooving' => 'канавочная', 'holder_threading' => 'резьбовая',
        'tool_holder' => 'держатель осевого инструмента', 'machine_jaw' => 'кулачки',
        'collet' => 'цанги', 'machine_vice' => 'тиски',
    ];

    private const STOP = [
        'пластина' => true, 'пластины' => true, 'пластину' => true, 'пластин' => true, 'пластиной' => true, 'для' => true, 'под' => true, 'точения' => true, 'обработки' => true, 'нужна' => true, 'нужен' => true, 'подбери' => true,
        'посоветуй' => true, 'какой' => true, 'какая' => true, 'купить' => true, 'есть' => true, 'в' => true, 'наличии' => true, 'на' => true, 'складе' => true, 'мне' => true,
        'надо' => true, 'хочу' => true, 'сверло' => true, 'сверла' => true, 'фреза' => true, 'фрезы' => true, 'метчик' => true, 'метчика' => true, 'державка' => true,
        'державки' => true, 'мм' => true, 'шт' => true, 'цена' => true, 'стоимость' => true, 'сколько' => true, 'стоит' => true, 'с' => true, 'и' => true, 'или' => true,
    ];

    public function __construct(string $text, array $insertPrefixes = [])
    {
        $this->text = trim($text);
        $this->low = Normalize::applyAliases(Normalize::low($this->text));
        $this->variants = Normalize::queryVariants($this->text);
        $this->compact = Normalize::compact($this->text);
        $this->insert_prefixes = $insertPrefixes;
        $this->parse();
    }

    private function parse(): void
    {
        $low = $this->low;
        $codeText = $this->text;
        $under = $this->parseCompatInsert();
        if ($under !== null) {
            $codeText = trim(mb_substr($this->text, 0, $under[0], 'UTF-8') . ' ' . mb_substr($this->text, $under[1], null, 'UTF-8'));
            $codeText = trim(preg_replace('/' . Compat::RE_PLATE_WORD . '/iu', ' ', $codeText));
        } elseif (preg_match('/' . Compat::RE_COMPAT_PHRASE . '/iu', $codeText)) {
            $codeText = trim(preg_replace('/' . Compat::RE_COMPAT_PHRASE . '/iu', ' ', $codeText));
        }
        if ($under !== null || preg_match('/' . Compat::RE_COMPAT_PHRASE . '/iu', $this->text)) {
            $this->compat_requested = true;
        }
        $low = Normalize::applyAliases(Normalize::low($codeText));

        if (preg_match('/\bпатрон|\bприжим/u', $low)) {
            $this->family = 'accessory';
        } elseif (preg_match('/калибр|инсайз|insize/u', $low)) {
            $this->family = 'accessory';
            $this->category_hints[] = 'measuring';
        } else {
            foreach (self::FAMILY_KEYWORDS as [$fam, $pattern]) {
                if (preg_match('/' . $pattern . '/u', $low)) {
                    $this->family = $fam;
                    break;
                }
            }
        }
        if ($this->family === 'insert' && preg_match('/сверл/u', $low)) {
            $iDrill = mb_strpos($low, 'сверл');
            $iPlate = mb_strpos($low, 'пластин');
            if ($iPlate === false || $iDrill < $iPlate) {
                $this->family = 'drill';
            }
        }
        foreach (self::CATEGORY_HINTS[$this->family ?? ''] ?? [] as [$cat, $pattern]) {
            if (preg_match('/' . $pattern . '/u', $low)) {
                $this->category_hints[] = $cat;
            }
        }
        if ($this->family === 'mill' && preg_match('/шпоночн/u', $low)) {
            $this->attrs['flutes2'] = true;
            if (!in_array('end_mill', $this->category_hints, true)) {
                $this->category_hints[] = 'end_mill';
            }
        }

        if ($this->family === 'insert' || $this->family === 'holder') {
            $this->parsePlateSpec($low);
        }

        $m = [];
        if (preg_match('/(?<![A-Za-z0-9])SBHA\)?\s*(\d{2})(?:\s*[-–]\s*|\s+)(\d{2})(?:\s*[-–]\s*(\d{2,3}))?/iu', $this->text, $m, PREG_UNMATCHED_AS_NULL)) {
            $this->family = 'accessory';
            if (!in_array('tool_holder', $this->category_hints, true)) {
                $this->category_hints[] = 'tool_holder';
            }
            $this->attrs['shank_mm'] = (float)$m[1];
            $this->attrs['clamp_mm'] = (float)$m[2];
            if ($m[3] !== null && $m[3] !== '') {
                $this->attrs['length_mm'] = (float)$m[3];
            }
        } elseif (preg_match('/(?<![A-Za-z0-9])SBHA(?![A-Za-z])/iu', $this->text)) {
            $this->family = 'accessory';
            if (!in_array('tool_holder', $this->category_hints, true)) {
                $this->category_hints[] = 'tool_holder';
            }
            $one = [];
            if (preg_match('/(?<![A-Za-z0-9])SBHA\)?\s*(\d{2})(?!\d)/iu', $this->text, $one)) {
                $this->attrs['shank_mm'] = (float)$one[1];
            }
        }

        if ($this->family === 'accessory' && in_array('machine_jaw', $this->category_hints, true)) {
            $jm = [];
            if (preg_match('/(?<![A-Za-zА-Яа-яЁё0-9])([A-Za-zА-Яа-яЁё])(\d{2})\s*[-–]\s*(\d{2,3})(?!\d)/u', $low, $jm)) {
                $this->attrs['jaw_series'] = strtoupper(Normalize::homoglyphLatin($jm[1])) . $jm[2];
                $this->attrs['jaw_size'] = (int)$jm[3];
            }
        }

        if ($this->family === 'accessory') {
            $this->parseAccessory($low);
        }

        $revHolder = null;
        if ($this->family === 'insert') {
            $hm = [];
            if (preg_match('/' . Compat::RE_HOLDER_MENTION . '/iu', $this->text, $hm, PREG_OFFSET_CAPTURE)) {
                $endByte = $hm[0][1] + strlen($hm[0][0]);
                $endChar = mb_strlen(substr($this->text, 0, $endByte), 'UTF-8');
                $revHolder = Codes::holderCodeFromText(mb_substr($this->text, $endChar, null, 'UTF-8'));
                $info = $revHolder !== null ? Compat::holderInsertCompat($revHolder) : null;
                if ($revHolder !== null && $info && !empty($info['size'])) {
                    $this->holder_compat_requested = true;
                    $this->holder_code = $revHolder;
                    $this->holder_compat = $info;
                    $this->holder_compat_code = $revHolder;
                }
            }
        }

        if ($this->family === null || $this->family === 'insert') {
            $cands = [];
            $vars = $under ? Normalize::queryVariants($codeText) : $this->variants;
            foreach ($vars as $v) {
                $c = Codes::insertCodeFromText($v);
                if ($c !== null && !str_starts_with(Normalize::compact($revHolder ?? ''), Normalize::compact($c))
                    && !in_array($c, $cands, true)) { $cands[] = $c; }
            }
            foreach ($cands as $c) {                       // приоритет — префикс, известный каталогу
                $p4 = substr($c, 0, 4);
                if (isset($this->insert_prefixes[$p4]) || isset(Codes::COMMON_INSERT_PREFIXES[$p4])) {
                    $this->insert_code = $c; $this->family = 'insert'; break;
                }
            }
            if ($this->insert_code === null && $cands) {   // иначе первый структурно валидный
                $this->insert_code = $cands[0]; $this->family = 'insert';
            }
        }
        if ($this->insert_code === null && ($this->family === null || $this->family === 'insert')) {
            $vars = $under !== null ? Normalize::queryVariants($codeText) : $this->variants;
            foreach ($vars as $v) {
                $m = [];
                if (preg_match('/(?<![A-Za-z0-9])([A-Z]{2,5})\s?(\d{2})([A-Z]\d{2,4})?(?![A-Za-z0-9])/u', strtoupper($v), $m, PREG_UNMATCHED_AS_NULL) !== 1) {
                    continue;
                }
                $pref = $m[1];
                if (!Codes::isShape($pref[0]) || !str_contains(Codes::ISO_CLEARANCE, $pref[1])
                    || isset(Codes::HOLDER_PREFIXES[$pref]) || Iso5608::parseHolderCode($pref . $m[2]) !== null) {
                    continue;
                }
                if (!isset(Codes::COMMON_INSERT_PREFIXES[$pref]) && !isset($this->insert_prefixes[$pref])) {
                    continue;
                }
                $this->insert_code = $pref . $m[2];
                $this->attrs['insert_prefix'] = $pref;
                $this->attrs['size_code'] = $m[2];
                if ($m[3] !== null && $m[3] !== '') {
                    $this->attrs['iso_tail'] = $m[3];
                }
                $this->family = 'insert';
                break;
            }
        }
        if ($this->family === null || $this->family === 'holder') {
            $vars = Normalize::queryVariants($codeText);
            foreach ($vars as $v) {
                $code = Codes::holderCodeFromText($v);
                if ($code !== null) {
                    $this->holder_code = $code;
                    if ($this->family === null) {
                        $this->family = 'holder';
                    }
                    break;
                }
            }
        }

        if ($this->family === 'insert' && $this->insert_code === null && preg_match('/' . Compat::RE_HOLDER_MENTION . '/iu', $this->text)) {
            $this->holder_compat_requested = true;
        }

        if ($this->family === 'insert') {
            $this->parseInsertGrades($low);
        }

        $b = [];
        if (preg_match('/(?:бренд|марка|производител[ья])\s*[:—-]?\s*([a-zа-я0-9-]{2,20})/u', $low, $b)) {
            $this->brand = $b[1];
        }

        $common = CatalogAttrs::extractCommon($low);
        $thread = $this->family === 'holder' ? [] : CatalogAttrs::extractThread($this->text);
        if ($thread) {
            $this->thread = $thread['thread'] ?? null;
            foreach (['pitch_mm', 'diameter_mm', 'thread_type', 'tap_kind'] as $key) {
                if (isset($thread[$key])) {
                    $this->attrs[$key] = $thread[$key];
                }
            }
        }
        foreach ($common as $k => $v) {
            if (!array_key_exists($k, $this->attrs) && $k !== 'grade') {
                $this->attrs[$k] = $v;
            }
        }

        // B5: материал обработки для drill/mill/reamer — по словам запроса
        if (in_array($this->family, ['drill', 'mill', 'reamer'], true)) {
            $mi = Normalize::materialIso($low);
            if ($mi !== null && !array_key_exists('iso_group', $this->attrs)) {
                $this->attrs['iso_group'] = $mi;
            }
            $toolMaterial = null;
            if (str_contains($low, 'нержав') || str_contains($low, 'inox')) {
                $toolMaterial = 'HSS-E';
            } elseif (str_contains($low, 'твердосплав') || str_contains($low, 'vhm')) {
                $toolMaterial = 'твердый сплав';
            } elseif (str_contains($low, 'сталь') || str_contains($low, 'hss')) {
                $toolMaterial = 'HSS';
            } elseif (str_contains($low, 'чугун')) {
                $toolMaterial = 'HSS';
            } elseif (str_contains($low, 'алюмин')) {
                $toolMaterial = 'HSS';
            } elseif (str_contains($low, 'титан')) {
                $toolMaterial = 'твердый сплав';
            }
            if ($toolMaterial !== null && !array_key_exists('material', $this->attrs)) {
                $this->attrs['material'] = $toolMaterial;
            }
        }

        // B6: сленг и назначение
        if (str_contains($low, 'кукуруза')) {
            $this->attrs['operation'] = 'roughing';
            if (!in_array('end_mill', $this->category_hints, true)) {
                $this->category_hints[] = 'end_mill';
            }
        }
        if (str_contains($low, 'ласточкин')) {
            if (!in_array('dovetail_mill', $this->category_hints, true)) {
                $this->category_hints[] = 'dovetail_mill';
            }
        }
        if (str_contains($low, 'глухое') && str_contains($low, 'отверстие')) {
            $this->attrs['tap_kind'] = 'blind';
        }

        $teeth = CatalogAttrs::extractTeeth($this->text);
        if ($teeth === null) {
            $m = [];
            if (preg_match('/(?<![\w.])(\d{1,2})\s*T(?![A-Za-zА-Яа-я0-9])/u', $this->text, $m) !== 1) {
                preg_match('/(?<![\w.])(\d{1,2})\s*Z(?![A-Za-zА-Яа-я0-9])/iu', $this->text, $m);
            }
            if ($m && (int)$m[1] > 0 && (int)$m[1] <= 40) {
                $teeth = (int)$m[1];
            }
        }
        if ($teeth) {
            $this->attrs['teeth'] = $teeth;
        }

        $fm = [];
        if (preg_match('/(?<![\w.])(\d{2,3})\s*-\s*(\d{1,3})\s*-\s*(\d{1,2})\s*T(?![A-Za-zА-Яа-я])/iu', $this->text, $fm) && $this->family === 'mill') {
            $this->attrs['diameter_mm'] = (float)$fm[1];
            $this->attrs['bore_mm'] = (float)$fm[2];
            $this->attrs['teeth'] = (int)$fm[3];
            unset($this->attrs['radius_mm']);
        }

        $dia = [];
        if (preg_match('/' . CatalogAttrs::RE_DIA . '/iu', $this->text, $dia)) {
            $this->attrs['diameter_mm'] = (float)str_replace(',', '.', $dia[1]);
        } elseif (in_array($this->family, ['drill', 'mill', 'reamer', 'countersink', 'saw'], true)) {
            $mm = [];
            $dims = CatalogAttrs::dims($this->text);
            if (preg_match('/' . CatalogAttrs::RE_MM . '/iu', $this->text, $mm)) {
                $this->attrs['diameter_mm'] = (float)str_replace(',', '.', $mm[1]);
            } elseif ($dims) {
                $this->attrs['diameter_mm'] = $dims[0];
            }
        }

        if (in_array($this->family, ['drill', 'mill'], true) && str_contains($low, 'диаметр')) {
            $after = explode('диаметр', $low, 2)[1];
            $m = [];
            if (preg_match('/(\d+(?:[.,]\d+)?)/u', $after, $m)) {
                $this->attrs['diameter_mm'] = (float)str_replace(',', '.', $m[1]);
            }
        }

        if (!array_key_exists('diameter_mm', $this->attrs) && in_array($this->family, ['drill', 'mill', 'reamer', 'countersink', 'saw'], true)) {
            $teeth = $this->attrs['teeth'] ?? null;
            $nominal = !empty($this->attrs['thread_type']) ? ($this->attrs['diameter_mm'] ?? null) : null;
            $mm = [];
            preg_match_all('/(?<![A-Za-zА-Яа-я0-9.])(\d+(?:[.,]\d+)?)(?![A-Za-zА-Яа-я0-9.,])/u', $this->text, $mm);
            foreach ($mm[1] as $raw) {
                $val = (float)str_replace(',', '.', $raw);
                if (!($val >= 0.3 && $val <= 500)) {
                    continue;
                }
                if ($teeth && $val == $teeth) {
                    continue;
                }
                if ($nominal !== null && abs($val - (float)$nominal) < 1e-9) {
                    continue;
                }
                $this->attrs['diameter_mm'] = $val;
                break;
            }
        }

        if ($this->family === 'drill' && $this->thread && preg_match('/под\s+(резьб|метчик)/u', $low)) {
            $td = Compat::tapDrillFor($this->thread);
            if ($td) {
                $this->attrs['diameter_mm'] = $td['drill_mm'];
                $this->attrs['tap_drill_for'] = $this->thread;
            }
        }

        if (in_array($this->family, ['drill', 'mill'], true)) {
            $ld = [];
            if (preg_match('/(?<![A-Za-z0-9])(\d{1,2})\s*[Dd](?![A-Za-z0-9])/u', $this->text, $ld) && (int)$ld[1] >= 1 && (int)$ld[1] <= 30) {
                $this->attrs['ld_ratio'] = (int)$ld[1];
            }
            $ang = [];
            if (preg_match('/(?<!\d)(\d{2,3})\s*(?:°|град)/u', $this->text, $ang) && (int)$ang[1] >= 45 && (int)$ang[1] <= 180) {
                $this->attrs['angle_deg'] = (float)$ang[1];
            }
        }

        $r = [];
        if (preg_match('/(?<![A-Za-zА-Яа-я0-9])R\s*(\d+(?:[.,]\d+)?)/iu', $this->text, $r)) {
            $this->attrs['radius_mm'] = (float)str_replace(',', '.', $r[1]);
        }

        $m = [];
        if (preg_match('/(?:хв\.?\s*|хвост[а-яё]*\s*)(\d{1,3}(?:[.,]\d+)?)(?!\d)/u', $low, $m) !== 1) {
            preg_match('/\bпод\s+(\d{1,3}(?:[.,]\d+)?)\s*(?:мм\s*)?(?:хв\.?|хвост[а-яё]*)/u', $low, $m);
        }
        if ($m) {
            $val = (float)str_replace(',', '.', $m[1]);
            if ($val >= 1 && $val <= 200) {
                if (in_array('tool_holder', $this->category_hints, true)) {
                    $this->attrs['clamp_mm'] = $val;
                } else {
                    $this->attrs['shank_mm'] = $val;
                    $this->shank_round = true;
                }
            }
        }

        if ($this->family === 'holder' && !array_key_exists('shank_mm', $this->attrs)) {
            $m = [];
            if (preg_match('/(?<![A-Za-zА-Яа-яЁё0-9])[SCEHСЕН](\d{2})(?![A-Za-zА-Яа-яЁё0-9])/iu', $codeText, $m) && (int)$m[1] >= 8 && (int)$m[1] <= 50) {
                if (Normalize::compact($this->holder_code ?? '') === Normalize::compact($m[0])) {
                    $this->holder_code = null;
                }
                $this->attrs['shank_mm'] = (float)$m[1];
                $this->shank_round = true;
            }
        }

        $dims = CatalogAttrs::dims($this->text);
        if ($this->family === 'holder' && !array_key_exists('shank_mm', $this->attrs)) {
            $sec = [];
            if (preg_match('/(?<!\d)(\d{2})(\d{2})(?!\d)/u', $codeText, $sec) && $sec[1] === $sec[2] && (int)$sec[1] >= 8 && (int)$sec[1] <= 50) {
                $this->attrs['shank_mm'] = (float)$sec[1];
                $this->attrs['shank_section'] = $sec[0];
            }
        }
        if ($dims && $this->family === 'holder' && !array_key_exists('shank_mm', $this->attrs)) {
            $this->attrs['shank_mm'] = $dims[0];
        }

        // B7: голое число для holder → диаметр хвоста (расточная → Ø, наружная → сечение)
        if ($this->family === 'holder' && !array_key_exists('shank_mm', $this->attrs)) {
            $m = [];
            if (preg_match_all('/(?<![\d.])\b(\d{2})\b(?![\d.])/u', $this->text, $m, PREG_SET_ORDER)) {
                foreach ($m as $nm) {
                    $val = (int)$nm[1];
                    if ($val >= 8 && $val <= 50) {
                        $this->attrs['shank_mm'] = (float)$val;
                        break;
                    }
                }
            }
        }

        $m = [];
        if (preg_match('/(?:h8|h7|h9|h6)\b/u', $low, $m) && $this->family === 'reamer') {
            $this->attrs['tolerance'] = strtoupper($m[0]);
        }

        $m = [];
        if (preg_match('/(?:er|er-)\s?(\d{1,2})/u', $low, $m) && $this->family === 'accessory') {
            $this->attrs['collet_series'] = 'ER' . $m[1];
            $clamp = [];
            if (preg_match('/(?:er-?\d{1,2})(?!\d)\D{0,4}(\d{1,2}(?:[.,]\d)?)\s*(?:мм)?\b/u', $low, $clamp)) {
                $this->attrs['clamp_mm'] = (float)str_replace(',', '.', $clamp[1]);
            }
        }

        if ($this->family === 'mill' && (str_contains($low, 'дисков') || str_contains($low, 'пазов') || str_contains($low, 'отрезн'))) {
            $dims = CatalogAttrs::dims($this->text);
            if (count($dims) >= 2 && $dims[1] <= 20) {
                $this->attrs['thickness_mm'] = $dims[1];
            }
        }

        $m = [];
        if (preg_match('/(\d+(?:[.,]\d+)?)\s*(?:мм)?\s*(?:диаметр|ø|⌀)/u', $low, $m)
            && !array_key_exists('diameter_mm', $this->attrs) && in_array($this->family, ['drill', 'mill', 'reamer'], true)) {
            $this->attrs['diameter_mm'] = (float)str_replace(',', '.', $m[1]);
        }

        $tokens = Normalize::tokenize(Normalize::applyAliases($this->text));
        $free = [];
        foreach ($tokens as $t) {
            if (!isset(self::STOP[$t]) && mb_strlen($t, 'UTF-8') > 1 && !Normalize::fullmatch('\d+[.,]?\d*', $t)) {
                $free[] = $t;
            }
        }
        if ($this->compat_insert !== null) {
            $ci = Normalize::lower($this->compat_insert);
            $free = array_values(array_filter($free, static fn($t) => $t !== $ci));
        }
        if ($this->holder_compat_code !== null) {
            $hc = Normalize::compact($this->holder_compat_code);
            $free = array_values(array_filter($free, static fn($t) => !str_contains($hc, Normalize::compact($t))));
        }
        $this->free_tokens = $free;
    }

    private function parseAccessory(string $low): void
    {
        if (in_array('measuring', $this->category_hints, true)) {
            $cm = [];
            if (preg_match('/(?<![\d-])(\d{4}-\d{2,4})(?![\d-])/u', $low, $cm)) {
                $this->attrs['measure_code'] = $cm[1];
            }
            $tol = [];
            if (preg_match('/(?<![a-zа-я0-9])([hн])\s*(\d{1,2})(?![\d.])/u', $low, $tol)) {
                $this->attrs['tolerance'] = 'H' . $tol[2];
            }
        }
        if (preg_match('/самозажимн/u', $low)) {
            $this->attrs['self_tightening'] = true;
            $cr = [];
            if (preg_match('/(?<![\d-])(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(?:мм)?/u', $low, $cr)) {
                $this->attrs['chuck_max_mm'] = (int)$cr[2];
            }
        }
        $mr = [];
        if (preg_match('/морзе\s*(\d{1,2})\s*на\s*морзе\s*(\d{1,2})/u', $low, $mr) !== 1) {
            preg_match('/(?<![\d\/])(\d{1,2})\s*\/\s*(\d{1,2})(?![\d\/])/u', $low, $mr);
        }
        if ($mr && str_contains($low, 'втулк')) {
            $this->attrs['morse_from'] = (int)$mr[1];
            $this->attrs['morse_to'] = (int)$mr[2];
            if (preg_match('/\bс\s+лапк/u', $low)) {
                $this->attrs['with_tang'] = true;
            }
        }
        if (str_contains($low, 'барпуллер')) {
            $this->attrs['bar_puller'] = true;
            $sq = [];
            if (preg_match('/(?<!\d)(\d{2})(\d{2})(?!\d)/u', $low, $sq) && $sq[1] === $sq[2]) {
                $this->attrs['bar_shank_mm'] = (int)$sq[1];
            }
        }
        $tm = [];
        if (preg_match('/(?<![a-zа-я0-9])(hsk|bt|бт|sk|nt|din)[\s-]?(\d{2})(?!\d)/u', $low, $tm)) {
            $map = ['бт' => 'BT', 'bt' => 'BT', 'hsk' => 'HSK', 'sk' => 'SK', 'nt' => 'NT', 'din' => 'DIN'];
            $this->attrs['taper'] = $map[$tm[1]] . $tm[2];
        }
        if (preg_match('/велдон|weldon/u', $low)) {
            $this->attrs['weldon'] = true;
            $dm = [];
            if (preg_match('/(?:велдон|weldon)\D{0,12}?(\d{1,2}(?:[.,]\d+)?)(?!\d)/u', $low, $dm) !== 1) {
                preg_match('/(?<!\d)(\d{1,2}(?:[.,]\d+)?)\s*(?:мм\s*)?(?:велдон|weldon)/u', $low, $dm);
            }
            if ($dm) {
                $val = (float)str_replace(',', '.', $dm[1]);
                $this->attrs['tool_d_mm'] = $val == (int)$val ? (int)$val : $val;
            }
        }
        $lm = [];
        if (preg_match('/(?:длин[а-яё]*|длиной)[\s:.—-]*(\d{2,3})(?!\d)/u', $low, $lm)) {
            $this->attrs['tool_l_mm'] = (int)$lm[1];
        }
        $vm = [];
        if (preg_match('/(?<![a-z])vdi\s*(\d{1,2})(?!\d)/u', $low, $vm)) {
            $this->attrs['chuck_system'] = 'VDI' . $vm[1];
        }
        $bm = [];
        if (preg_match('/(?<![a-z0-9])b\s?(\d{2})(?!\d)/u', $low, $bm) && str_contains($low, 'патрон')) {
            $this->attrs['chuck_taper'] = 'B' . $bm[1];
        }
        if (preg_match('/\bприжим/u', $low)) {
            $this->attrs['clamp_set'] = true;
            $sm = [];
            if (preg_match('/(?<!\d)(\d{1,2})\s*(?:мм\s*)?паз/u', $low, $sm) !== 1) {
                preg_match('/паз\.?\s*(\d{1,2})(?!\d)/u', $low, $sm);
            }
            if ($sm) {
                $this->attrs['slot_mm'] = (int)$sm[1];
            }
        }
    }

    private function parseInsertGrades(string $low): void
    {
        $up = str_replace('Ё', 'Е', mb_strtoupper($this->text, 'UTF-8'));
        $mm = [];
        preg_match_all('/(?<![\w.])(\d{4}|[A-Z]{1,3}\d{3,4})(?![\w.])/u', $up, $mm);
        foreach ($mm[1] as $g1) {
            if ($this->insert_code !== null && str_contains($this->insert_code, $g1)) {
                continue;
            }
            if (!$this->holder_compat_requested) {
                // B11: убрать буквенный префикс у марки (PM4325 → 4325)
                $gradeVal = preg_replace('/^[A-Z]+/', '', $g1);
                $this->attrs['grade'] = $gradeVal !== '' ? $gradeVal : $g1;
            }
            break;
        }
        if (!array_key_exists('grade', $this->attrs) && $this->insert_code !== null) {
            $g2 = [];
            if (preg_match('/(?<![\w.])([A-Z]{1,2}\d{2})(?![\w.])/u', $up, $g2) && !str_contains($this->insert_code, $g2[1])) {
                $gradeVal = preg_replace('/^[A-Z]+/', '', $g2[1]);
                $this->attrs['grade'] = $gradeVal !== '' ? $gradeVal : $g2[1];
            }
        }
        $isoG = [];
        if (preg_match('/(?<![\w.])([PMKNSH])\s?(\d{1,2})(?![\w.])/u', $up, $isoG)) {
            $this->attrs['iso_group'] = $isoG[1];
        }
        if (!array_key_exists('iso_group', $this->attrs)) {
            $mi = Normalize::materialIso($low);
            if ($mi !== null) {
                $this->attrs['iso_group'] = $mi;
            }
        }
        $op = Normalize::operationFromText($low);
        if ($op !== null) {
            $this->attrs['operation'] = $op;
        }
    }

    private function parsePlateSpec(string $low): void
    {
        foreach (Codes::PLATE_SHAPE_WORDS as [$pattern, $letter]) {
            if (preg_match('/' . $pattern . '/u', $low)) {
                $this->attrs['plate_shape'] = $letter;
                break;
            }
        }
        $m = [];
        if (preg_match('/размер\w*\s*[:.—-]?\s*(\d{1,2})(?!\d)/u', $low, $m)) {
            $this->attrs['plate_size'] = str_pad($m[1], 2, '0', STR_PAD_LEFT);
        }
        $r = [];
        if (preg_match('/радиус\w*\s*[:.—-]?\s*(\d{2}(?:[.,]\d+)?|\d+[.,]\d+|\d{1,2})(?!\d)/u', $low, $r)) {
            $raw = str_replace(',', '.', $r[1]);
            $val = (strlen($raw) === 2 && ctype_digit($raw)) ? (int)$raw / 10.0 : (float)$raw;
            if ($val > 0 && $val <= 10) {
                $this->attrs['corner_radius_mm'] = $val;
            }
        }
        if ($this->family === 'holder') {
            if (preg_match('/\bправ/u', $low)) {
                $this->attrs['hand'] = 'R';
            } elseif (preg_match('/\bлев/u', $low)) {
                $this->attrs['hand'] = 'L';
            }
            if ($this->compat_requested && !empty($this->attrs['plate_shape']) && !empty($this->attrs['plate_size'])) {
                $this->compat_shape = $this->attrs['plate_shape'];
                $this->compat_size = $this->attrs['plate_size'];
                $this->compat_hand = $this->attrs['hand'] ?? null;
            }
        }
    }

    /** @return array{0:int,1:int}|null char-span фрагмента «под <код>» */
    private function parseCompatInsert(): ?array
    {
        $mm = [];
        preg_match_all('/' . Compat::RE_UNDER_INSERT . '/iu', $this->text, $mm, PREG_OFFSET_CAPTURE | PREG_UNMATCHED_AS_NULL);
        $n = count($mm[0]);
        for ($k = 0; $k < $n; $k++) {
            $full = $mm[0][$k][0];
            $byteOff = $mm[0][$k][1];
            $g1 = $mm[1][$k][0];
            $g2 = $mm[2][$k][0] ?? '';
            $raw = Normalize::low($g1);
            if (in_array($raw, ['резьбу', 'резьбы', 'пластину', 'пластины', 'пластин', 'метчика', 'метчик'], true)) {
                continue;
            }
            $word = Codes::insertPrefixFromWord($g1, $this->insert_prefixes);
            $digits = $g2 ?? '';
            if ($word === null) {
                continue;
            }
            if ($digits === '' && !isset($this->insert_prefixes[$word]) && !isset(Codes::COMMON_INSERT_PREFIXES[$word])) {
                continue;
            }
            $this->setCompat($word . $digits);
            $start = mb_strlen(substr($this->text, 0, $byteOff), 'UTF-8');
            return [$start, $start + mb_strlen($full, 'UTF-8')];
        }
        return null;
    }

    public function setCompat(string $code): void
    {
        $info = Compat::insertCompatKey($code);
        if (!$info) {
            return;
        }
        $this->compat_insert = strtoupper($code);
        $this->compat_prefix = $info['prefix'];
        $this->compat_shape = $info['shape'];
        $this->compat_clearance = $info['clearance'];
        $this->compat_hole = $info['hole'] ?? null;
        $this->compat_size = $info['size'];
    }

    /** toArray: представление для сравнения/отладки. */
    public function toArray(): array
    {
        return [
            'text' => $this->text, 'family' => $this->family, 'category_hints' => $this->category_hints,
            'attrs' => $this->attrs, 'insert_code' => $this->insert_code, 'holder_code' => $this->holder_code,
            'thread' => $this->thread, 'brand' => $this->brand, 'free_tokens' => $this->free_tokens,
            'compat_insert' => $this->compat_insert, 'compat_prefix' => $this->compat_prefix,
            'compat_shape' => $this->compat_shape, 'compat_clearance' => $this->compat_clearance,
            'compat_hole' => $this->compat_hole, 'compat_size' => $this->compat_size, 'compat_hand' => $this->compat_hand,
            'compat_requested' => $this->compat_requested, 'holder_compat' => $this->holder_compat,
            'holder_compat_code' => $this->holder_compat_code, 'holder_compat_requested' => $this->holder_compat_requested,
            'shank_round' => $this->shank_round,
        ];
    }
}