<?php
/**
 * Прокси qtool.ru -> сервис подбора (Python на 127.0.0.1:8000).
 *
 * POST ai.php   {"q": "CNMG 120408 для стали"}                    — подбор
 * POST ai.php   {"action": "feedback", "rating": "like", "query": "...", "answer": "..."}
 * POST ai.php   {"action": "clear"}                               — сбросить контекст диалога
 * GET  ai.php?action=status                                       — сводка по каталогу (кэш 60 с)
 *
 * Настройка PHP-FPM: env[AI_INTERNAL_URL] = http://127.0.0.1:8000, env[AI_TIMEOUT] = 10
 * На стороне Python обязателен TRUST_PROXY=1 (иначе лимит запросов считается на весь сайт разом).
 */
declare(strict_types=1);

ini_set('display_errors', '0');
header_remove('X-Powered-By');

const AI_STATUS_TTL = 60;
const AI_BODY_LIMIT = 65536;
const AI_QUERY_LIMIT = 1000;
const AI_SID_COOKIE = 'qai_sid';

$AI_URL = rtrim((string)(getenv('AI_INTERNAL_URL') ?: 'http://127.0.0.1:8000'), '/');
$AI_TIMEOUT = max(2, min(30, (int)(getenv('AI_TIMEOUT') ?: 10)));

function ai_out(int $code, string $json): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    header('Content-Length: ' . strlen($json));
    echo $json;
    exit;
}

function ai_json(int $code, array $data): void
{
    ai_out($code, (string)json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
}

function ai_error(int $code, string $message): void
{
    ai_json($code, ['error' => $message]);
}

function ai_is_json(string $raw): bool
{
    json_decode($raw, true);
    return json_last_error() === JSON_ERROR_NONE;
}

function ai_pass(int $code, string $raw): void
{
    if (!ai_is_json($raw)) {
        error_log('qtool-ai: сервис вернул не JSON: ' . substr($raw, 0, 200));
        ai_error(502, 'Подбор вернул некорректный ответ');
    }
    ai_out($code, $raw);
}

function ai_cut(string $s, int $max): string
{
    return function_exists('mb_substr') ? mb_substr($s, 0, $max, 'UTF-8') : substr($s, 0, $max);
}

function ai_check_origin(): void
{
    // Fetch с чужого сайта приходит с чужим Origin: без проверки форму дёргали бы со стороны
    $origin = (string)($_SERVER['HTTP_ORIGIN'] ?? '');
    if ($origin === '') {
        return;
    }
    $oh = strtolower((string)parse_url($origin, PHP_URL_HOST));
    $hh = strtolower((string)($_SERVER['HTTP_HOST'] ?? ''));
    $hh = (string)preg_replace('/:\d+$/', '', $hh);
    $oh = (string)preg_replace('/^www\./', '', $oh);
    $hh = (string)preg_replace('/^www\./', '', $hh);
    if ($oh === '' || $hh === '' || $oh !== $hh) {
        ai_error(403, 'Запрос с чужого сайта отклонён');
    }
}

function ai_client_ip(): string
{
    // Только REMOTE_ADDR: X-Forwarded-For от клиента подделать нельзя отсюда, а нам нужен
    // реальный посетитель для лимита запросов на стороне Python
    $ip = (string)($_SERVER['REMOTE_ADDR'] ?? '');
    return filter_var($ip, FILTER_VALIDATE_IP) ? $ip : '0.0.0.0';
}

function ai_session_id(): string
{
    if (session_status() === PHP_SESSION_NONE) {
        if (@session_start()) {
            session_write_close();  // сессию только читаем, файловую блокировку держать незачем
        }
    }
    $raw = (string)session_id();
    if ($raw === '' && isset($_COOKIE[AI_SID_COOKIE]) && is_string($_COOKIE[AI_SID_COOKIE])) {
        $raw = (string)$_COOKIE[AI_SID_COOKIE];
    }
    if ($raw === '') {
        // Прямое подключение без сессии сайта: свой стабильный идентификатор посетителя
        $raw = bin2hex(random_bytes(16));
        setcookie(AI_SID_COOKIE, $raw, [
            'expires' => time() + 2592000,
            'path' => '/',
            'httponly' => true,
            'samesite' => 'Lax',
            'secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
        ]);
    }
    return strtoupper(substr(hash('sha256', $raw . '|qtool-ai'), 0, 16));
}

function ai_request(string $url, string $path, ?array $payload, int $timeout): array
{
    $ch = curl_init($url . $path);
    $headers = ['Accept: application/json'];
    $opts = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 2,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_PROTOCOLS => CURLPROTO_HTTP,
    ];
    if ($payload === null) {
        $opts[CURLOPT_HTTPGET] = true;
    } else {
        $headers[] = 'Content-Type: application/json';
        $headers[] = 'X-Forwarded-For: ' . ai_client_ip();
        $opts[CURLOPT_POST] = true;
        $opts[CURLOPT_POSTFIELDS] = (string)json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }
    $opts[CURLOPT_HTTPHEADER] = $headers;
    curl_setopt_array($ch, $opts);
    $raw = curl_exec($ch);
    $errno = curl_errno($ch);
    $err = curl_error($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    if ($raw === false || $errno !== 0) {
        error_log('qtool-ai: curl ' . $errno . ' ' . $err);
        return [503, (string)json_encode(['error' => 'Подбор временно недоступен — попробуйте через минуту.'], JSON_UNESCAPED_UNICODE)];
    }
    return [$code > 0 ? $code : 502, (string)$raw];
}

function ai_cache_get(string $key): ?string
{
    if (function_exists('apcu_fetch')) {
        $v = apcu_fetch($key, $ok);
        return $ok && is_string($v) ? $v : null;
    }
    $f = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'qtool-ai-' . sha1($key) . '.json';
    if (!is_file($f) || time() - (int)filemtime($f) >= AI_STATUS_TTL) {
        return null;
    }
    $v = @file_get_contents($f);
    return is_string($v) && $v !== '' ? $v : null;
}

function ai_cache_set(string $key, string $json): void
{
    if (function_exists('apcu_store')) {
        apcu_store($key, $json, AI_STATUS_TTL);
        return;
    }
    $f = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'qtool-ai-' . sha1($key) . '.json';
    @file_put_contents($f, $json, LOCK_EX);
}

function ai_public_status(string $raw): string
{
    // Сервис видит запрос с loopback и считает его локальным: админ-флаги наружу не отдаём
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return $raw;
    }
    unset($data['local_admin'], $data['llm_on']);
    return (string)json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

$method = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
$action = strtolower(trim((string)($_GET['action'] ?? '')));

if ($method === 'GET') {
    if ($action !== 'status') {
        ai_error(405, 'Метод не поддерживается');
    }
    $cacheKey = 'qtool-ai-status:' . $AI_URL;
    $cached = ai_cache_get($cacheKey);
    if ($cached !== null) {
        ai_out(200, $cached);
    }
    [$code, $raw] = ai_request($AI_URL, '/api/status', null, min(5, $AI_TIMEOUT));
    if ($code === 200 && ai_is_json($raw)) {
        $raw = ai_public_status($raw);
        ai_cache_set($cacheKey, $raw);
    }
    ai_pass($code, $raw);
}

if ($method !== 'POST') {
    ai_error(405, 'Метод не поддерживается');
}
ai_check_origin();

if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > AI_BODY_LIMIT) {
    ai_error(413, 'Слишком большой запрос');
}
$body = json_decode((string)file_get_contents('php://input'), true);
if (!is_array($body)) {
    ai_error(400, 'Некорректный JSON');
}

$action = strtolower(trim((string)($body['action'] ?? ($action !== '' ? $action : 'search'))));
$sid = ai_session_id();

if ($action === 'search') {
    $q = trim((string)($body['q'] ?? $body['query'] ?? ''));
    $len = function_exists('mb_strlen') ? mb_strlen($q, 'UTF-8') : strlen($q);
    if ($q === '' || $len > AI_QUERY_LIMIT) {
        ai_error(400, 'Запрос должен быть от 1 до ' . AI_QUERY_LIMIT . ' символов');
    }
    [$code, $raw] = ai_request($AI_URL, '/api/query', ['query' => $q, 'session_id' => $sid], $AI_TIMEOUT);
    ai_pass($code, $raw);
}

if ($action === 'feedback') {
    $rating = (string)($body['rating'] ?? '');
    if (!in_array($rating, ['like', 'warn', 'dislike'], true)) {
        ai_error(400, 'Некорректная оценка');
    }
    $payload = [
        'session_id' => $sid,
        'rating' => $rating,
        'comment' => ai_cut((string)($body['comment'] ?? ''), 400),
        'query' => ai_cut((string)($body['query'] ?? ''), 4000),
        'answer' => ai_cut((string)($body['answer'] ?? ''), 3000),
        'meta' => is_array($body['meta'] ?? null) ? $body['meta'] : [],
    ];
    [$code, $raw] = ai_request($AI_URL, '/api/feedback', $payload, min(5, $AI_TIMEOUT));
    ai_pass($code, $raw);
}

if ($action === 'clear') {
    [$code, $raw] = ai_request($AI_URL, '/api/clear_chat', ['session_id' => $sid], min(5, $AI_TIMEOUT));
    ai_pass($code, $raw);
}

ai_error(400, 'Неизвестное действие');
