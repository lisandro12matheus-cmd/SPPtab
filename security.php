<?php
declare(strict_types=1);

/** Shared browser/API boundary for the local SPPtab application. */
function tabwin2_security_headers(): void
{
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: SAMEORIGIN');
    header('Referrer-Policy: same-origin');
    header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'");
}

function tabwin2_scheme(): string
{
    return (!empty($_SERVER['HTTPS']) && strtolower((string) $_SERVER['HTTPS']) !== 'off') ? 'https' : 'http';
}

function tabwin2_normalize_authority(string $authority, string $scheme): ?string
{
    $authority = trim(strtolower($authority));
    if ($authority === '' || preg_match('/[\x00-\x20\x7f,@\\\\]/', $authority)) return null;
    $parts = parse_url($scheme . '://' . $authority);
    if (!is_array($parts) || empty($parts['host']) || isset($parts['user']) || isset($parts['pass']) || isset($parts['path']) || isset($parts['query']) || isset($parts['fragment'])) return null;
    $host = strtolower(trim((string) $parts['host'], '[]'));
    if ($host === '' || preg_match('/[^a-z0-9.:-]/', $host)) return null;
    $port = isset($parts['port']) ? (int) $parts['port'] : ($scheme === 'https' ? 443 : 80);
    if ($port < 1 || $port > 65535) return null;
    return $host . ':' . $port;
}

function tabwin2_host_allowed(): bool
{
    $host = (string) ($_SERVER['HTTP_HOST'] ?? '');
    $actual = tabwin2_normalize_authority($host, tabwin2_scheme());
    if ($actual === null) return false;
    $configured = getenv('TABWIN2_ALLOWED_HOSTS');
    $allowed = is_string($configured) && trim($configured) !== ''
        ? array_map('trim', explode(',', $configured))
        : ['localhost', 'localhost:80', 'localhost:443', '127.0.0.1', '127.0.0.1:80', '127.0.0.1:443', '[::1]', '[::1]:80', '[::1]:443'];
    foreach ($allowed as $entry) {
        $candidate = tabwin2_normalize_authority($entry, tabwin2_scheme());
        if ($candidate !== null && hash_equals($candidate, $actual)) return true;
    }
    return false;
}

function tabwin2_start_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) return;
    if (session_status() !== PHP_SESSION_NONE) throw new RuntimeException('A sessão local não pôde ser iniciada.');
    session_name('SPPTABSESSID');
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/',
        'secure' => tabwin2_scheme() === 'https',
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    if (!session_start()) throw new RuntimeException('A sessão local não pôde ser iniciada.');
    if (!isset($_SESSION['tabwin2_csrf']) || !is_string($_SESSION['tabwin2_csrf'])) {
        $_SESSION['tabwin2_csrf'] = bin2hex(random_bytes(32));
    }
}

function tabwin2_page_security(): void
{
    tabwin2_security_headers();
    header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
    if (!tabwin2_host_allowed()) {
        http_response_code(400);
        header('Content-Type: text/plain; charset=utf-8');
        exit('Endereço local inválido.');
    }
    tabwin2_start_session();
}

function tabwin2_csrf_token(): string
{
    tabwin2_start_session();
    return (string) $_SESSION['tabwin2_csrf'];
}

function tabwin2_register_download_tokens(array $response): void
{
    $urls = [];
    if (isset($response['savedRecords']['url']) && is_string($response['savedRecords']['url'])) $urls[] = $response['savedRecords']['url'];
    if (isset($response['result']['savedRecords']['url']) && is_string($response['result']['savedRecords']['url'])) $urls[] = $response['result']['savedRecords']['url'];
    $tokens = [];
    foreach ($urls as $url) {
        if (preg_match('/\Adownload\.php\?token=([a-f0-9]{32})\z/', $url, $match)) $tokens[] = $match[1];
    }
    if (!$tokens) return;
    tabwin2_start_session();
    $now = time();
    $grants = $_SESSION['tabwin2_download_tokens'] ?? [];
    if (!is_array($grants)) $grants = [];
    foreach ($grants as $token => $issuedAt) {
        if (!is_string($token) || !is_int($issuedAt) || $issuedAt < $now - 86400) unset($grants[$token]);
    }
    foreach ($tokens as $token) $grants[$token] = $now;
    if (count($grants) > 100) {
        asort($grants, SORT_NUMERIC);
        $grants = array_slice($grants, -100, null, true);
    }
    $_SESSION['tabwin2_download_tokens'] = $grants;
    session_write_close();
}

function tabwin2_download_token_allowed(string $token): bool
{
    tabwin2_start_session();
    $grants = $_SESSION['tabwin2_download_tokens'] ?? [];
    $issuedAt = is_array($grants) ? ($grants[$token] ?? null) : null;
    return is_int($issuedAt) && $issuedAt >= time() - 86400;
}

function tabwin2_api_guard(int $maxBytes = 1048576): string
{
    tabwin2_security_headers();
    header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
    if (!tabwin2_host_allowed()) {
        http_response_code(400);
        throw new RuntimeException('Endereço local inválido.');
    }
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        header('Allow: POST');
        http_response_code(405);
        throw new RuntimeException('Use uma solicitação POST.');
    }
    $contentType = strtolower(trim(explode(';', (string) ($_SERVER['CONTENT_TYPE'] ?? ''), 2)[0]));
    if ($contentType !== 'application/json') {
        http_response_code(415);
        throw new RuntimeException('Envie a solicitação no formato JSON.');
    }
    $origin = $_SERVER['HTTP_ORIGIN'] ?? null;
    if ($origin !== null) {
        if ($origin === 'null') {
            http_response_code(403);
            throw new RuntimeException('Origem da solicitação não autorizada.');
        }
        $parts = parse_url((string) $origin);
        $originAuthority = is_array($parts) && isset($parts['host']) ? tabwin2_normalize_authority(
            ((str_contains((string) $parts['host'], ':') && !str_starts_with((string) $parts['host'], '[')) ? '[' . $parts['host'] . ']' : (string) $parts['host']) . (isset($parts['port']) ? ':' . (int) $parts['port'] : ''),
            strtolower((string) ($parts['scheme'] ?? ''))
        ) : null;
        $hostAuthority = tabwin2_normalize_authority((string) ($_SERVER['HTTP_HOST'] ?? ''), tabwin2_scheme());
        if (!is_array($parts) || isset($parts['user']) || isset($parts['pass']) || isset($parts['path']) || isset($parts['query']) || isset($parts['fragment']) || strtolower((string) ($parts['scheme'] ?? '')) !== tabwin2_scheme() || $originAuthority === null || $hostAuthority === null || !hash_equals($hostAuthority, $originAuthority)) {
            http_response_code(403);
            throw new RuntimeException('Origem da solicitação não autorizada.');
        }
    }
    $fetchSite = strtolower((string) ($_SERVER['HTTP_SEC_FETCH_SITE'] ?? ''));
    if ($fetchSite === 'cross-site') {
        http_response_code(403);
        throw new RuntimeException('Origem da solicitação não autorizada.');
    }
    tabwin2_start_session();
    $expected = (string) $_SESSION['tabwin2_csrf'];
    $provided = (string) ($_SERVER['HTTP_X_SPPTAB_CSRF'] ?? '');
    if ($provided === '' || !hash_equals($expected, $provided)) {
        http_response_code(403);
        throw new RuntimeException('A sessão expirou. Atualize a página e tente novamente.');
    }
    $length = filter_var($_SERVER['CONTENT_LENGTH'] ?? null, FILTER_VALIDATE_INT);
    if ($length !== false && $length !== null && $length > $maxBytes) {
        http_response_code(413);
        throw new RuntimeException('A solicitação excede o tamanho permitido.');
    }
    $stream = fopen('php://input', 'rb');
    if ($stream === false) throw new RuntimeException('Não foi possível ler a solicitação.');
    $body = '';
    try {
        while (!feof($stream) && strlen($body) <= $maxBytes) {
            $chunk = fread($stream, min(65536, $maxBytes + 1 - strlen($body)));
            if ($chunk === false || $chunk === '') break;
            $body .= $chunk;
        }
    } finally {
        fclose($stream);
    }
    if (strlen($body) > $maxBytes) {
        http_response_code(413);
        throw new RuntimeException('A solicitação excede o tamanho permitido.');
    }
    session_write_close();
    return $body;
}

function tabwin2_validate_api_payload(array $payload): void
{
    $action = $payload['action'] ?? '';
    $pathActions = ['schema', 'delete_file', 'preset_list', 'preset_save', 'preset_get', 'preset_delete', 'convert_start'];
    if (in_array($action, $pathActions, true) && (!isset($payload['path']) || !is_string($payload['path']) || $payload['path'] === '' || strlen($payload['path']) > 600)) {
        http_response_code(400);
        throw new RuntimeException('O caminho do arquivo é inválido.');
    }
    if (in_array($action, ['convert_status', 'tabulate_status'], true) && (!isset($payload['job_id']) || !is_string($payload['job_id']) || !preg_match('/\A[a-f0-9]{32}\z/', $payload['job_id']))) {
        http_response_code(400);
        throw new RuntimeException('Identificador de processamento inválido.');
    }
    if (in_array($action, ['preset_get', 'preset_delete'], true) && (!isset($payload['preset_id']) || !is_string($payload['preset_id']) || !preg_match('/\A[a-f0-9]{24}\z/', $payload['preset_id']))) {
        http_response_code(400);
        throw new RuntimeException('Identificador da combinação inválido.');
    }
    $nameLength = isset($payload['name']) && is_string($payload['name']) ? preg_match_all('/./us', $payload['name']) : false;
    if ($action === 'preset_save' && (!isset($payload['name']) || !is_string($payload['name']) || trim($payload['name']) === '' || $nameLength === false || $nameLength > 80)) {
        http_response_code(400);
        throw new RuntimeException('Dê um nome com até 80 caracteres para a combinação.');
    }
    if ($action === 'download') {
        $names = $payload['names'] ?? null;
        if (!is_array($names) || count($names) < 1 || count($names) > 100) {
            http_response_code(400);
            throw new RuntimeException('Selecione até 100 arquivos válidos.');
        }
        foreach ($names as $name) {
            if (!is_string($name) || strlen($name) > 24 || !preg_match('/\A[A-Za-z0-9]{2,8}[A-Za-z]{2}\d{4}[A-Za-z]?\.dbc\z/i', $name)) {
                http_response_code(400);
                throw new RuntimeException('A seleção contém um nome de arquivo inválido.');
            }
        }
    }
    if (in_array($action, ['tabulate', 'tabulate_start'], true)) {
        if (isset($payload['sources']) && (!is_array($payload['sources']) || count($payload['sources']) > 100)) {
            http_response_code(400);
            throw new RuntimeException('A lista de arquivos da tabulação é inválida.');
        }
        if (isset($payload['filters']) && (!is_array($payload['filters']) || count($payload['filters']) > 300)) {
            http_response_code(400);
            throw new RuntimeException('A lista de filtros excede o limite permitido.');
        }
        if (isset($payload['sources'])) {
            foreach ($payload['sources'] as $source) {
                if (!is_array($source) || !isset($source['path']) || !is_string($source['path']) || strlen($source['path']) > 600 || (isset($source['dbfPath']) && (!is_string($source['dbfPath']) || strlen($source['dbfPath']) > 700))) {
                    http_response_code(400);
                    throw new RuntimeException('A lista de arquivos da tabulação é inválida.');
                }
            }
        }
    }
}
