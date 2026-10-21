<?php
declare(strict_types=1);

// The built-in PHP server ignores .htaccess, so expose only the app entry points
// and static assets. The server itself is bound to 127.0.0.1 by the launcher.
require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'security.php';
if (!tabwin2_host_allowed()) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Não encontrado.';
    return true;
}
$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
$path = is_string($uri) ? rawurldecode($uri) : '/';
$path = '/' . ltrim(str_replace('\\', '/', $path), '/');

if ($path === '/__tabwin2_health') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['ok' => true, 'php' => PHP_VERSION]);
    return true;
}

if ($path === '/' || preg_match('~^/(?:index|api|bases|tabular|minhas-tabulacoes|tabulacoes-prontas|resultado|download)\.php$~i', $path)) {
    return false;
}

if (preg_match('~^/assets/(?!.*(?:^|/)\.\.?/)[A-Za-z0-9._/-]+\.(?:css|js|svg|png|jpe?g|webp|ico|woff2?)$~i', $path)) {
    // This router lives under app/packaging, while the built-in server's
    // document root is app/. Resolve assets from that document root.
    $appRoot = dirname(__DIR__);
    $assetRoot = realpath($appRoot . DIRECTORY_SEPARATOR . 'assets');
    $asset = realpath($appRoot . str_replace('/', DIRECTORY_SEPARATOR, $path));
    if ($assetRoot !== false && $asset !== false
        && str_starts_with($asset, $assetRoot . DIRECTORY_SEPARATOR)
        && is_file($asset)) {
        return false;
    }
}

http_response_code(404);
header('Content-Type: text/plain; charset=utf-8');
echo 'Não encontrado.';
return true;
