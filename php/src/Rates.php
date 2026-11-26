<?php
declare(strict_types=1);

namespace Qtool;

/**
 * Курсы ЦБ РФ для пересчёта цен USD/EUR/GBP/CNY в рубли. Чистый PHP.
 * Курсы кэшируются в data/rates.json. Нет сети и кэша — цена в исходной валюте.
 * Порт src/rates.py.
 */
final class Rates
{
    public const RATES_URL = 'https://www.cbr-xml-daily.ru/daily_json.js';
    public const MAX_AGE_SEC = 12 * 3600;

    /** @var array<string,float> */
    private static array $rates = [];
    private static string $date = '';
    private static float $fetchedAt = 0.0;

    public static function ratesPath(): string
    {
        return dirname(__DIR__) . '/data/rates.json';
    }

    /** @return array<string,float> */
    public static function parseCbrJson(array $payload): array
    {
        $out = [];
        foreach (($payload['Valute'] ?? []) as $code => $v) {
            if (!is_array($v) || !isset($v['Value'])) {
                continue;
            }
            $nominal = (float)($v['Nominal'] ?? 1) ?: 1.0;
            $value = Storage::f($v['Value']);
            if ($value === null) {
                continue;
            }
            $out[strtoupper((string)$code)] = $value / $nominal;
        }
        return $out;
    }

    public static function loadCache(): void
    {
        $path = self::ratesPath();
        if (!is_file($path)) {
            return;
        }
        $d = json_decode((string)file_get_contents($path), true);
        if (!is_array($d)) {
            return;
        }
        self::$rates = is_array($d['rates'] ?? null) ? $d['rates'] : [];
        self::$date = (string)($d['date'] ?? '');
        self::$fetchedAt = (float)($d['fetched_at'] ?? 0);
    }

    public static function refresh(int $timeout = 10): bool
    {
        if (!function_exists('curl_init')) {
            return false;
        }
        $ch = curl_init(self::RATES_URL);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_HTTPHEADER => ['User-Agent: tool-advisor'],
        ]);
        $body = curl_exec($ch);
        curl_close($ch);
        if (!is_string($body)) {
            return false;
        }
        $payload = json_decode($body, true);
        if (!is_array($payload)) {
            return false;
        }
        $rates = self::parseCbrJson($payload);
        if (empty($rates['USD'])) {
            return false;
        }
        self::$rates = $rates;
        self::$date = substr((string)($payload['Date'] ?? ''), 0, 10);
        self::$fetchedAt = microtime(true);
        $dir = dirname(self::ratesPath());
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
        file_put_contents(self::ratesPath(), json_encode([
            'rates' => self::$rates, 'date' => self::$date, 'fetched_at' => self::$fetchedAt,
        ], JSON_UNESCAPED_UNICODE));
        return true;
    }

    public static function init(bool $background = true): void
    {
        self::loadCache();
        if (microtime(true) - self::$fetchedAt > self::MAX_AGE_SEC && getenv('SKIP_NETWORK_SYNC') !== '1') {
            self::refresh();
        }
    }

    public static function toRub(float $amount, string $currency): ?float
    {
        $cur = strtoupper($currency ?: 'RUB');
        if ($cur === 'RUB') {
            return $amount;
        }
        $rate = self::$rates[$cur] ?? null;
        return $rate ? round($amount * $rate, 2) : null;
    }

    public static function ratesDate(): string
    {
        return self::$date;
    }

    /** @param array<string,float> $rates */
    public static function setRatesForTests(array $rates, string $date = ''): void
    {
        self::$rates = $rates;
        self::$date = $date;
        self::$fetchedAt = microtime(true);
    }

    public static function priceDisplay(float $price, string $currency, bool $onRequest): string
    {
        if ($onRequest || $price <= 0) {
            return 'цена по запросу';
        }
        $cur = strtoupper($currency ?: 'RUB');
        $fmt = static fn(float $x): string => number_format($x, 0, '.', ' ');
        if ($cur === 'RUB') {
            return $fmt($price) . ' ₽';
        }
        $orig = number_format($price, 2, '.', ' ') . ' ' . $cur;
        if (getenv('ADVISOR_CONVERT_FX') !== '1') {
            return 'цена уточняется на сайте (в выгрузке: ' . $orig . ')';
        }
        $rub = self::toRub($price, $cur);
        if ($rub === null) {
            return $orig;
        }
        $d = self::ratesDate();
        $dTxt = strlen($d) >= 10 ? ', курс ЦБ ' . substr($d, 8, 2) . '.' . substr($d, 5, 2) : ', курс ЦБ';
        return '≈ ' . $fmt($rub) . ' ₽ (' . $orig . $dTxt . ')';
    }
}