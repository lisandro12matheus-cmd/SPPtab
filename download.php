<?php
declare(strict_types=1);
require_once __DIR__ . '/security.php';
tabwin2_security_headers();
if (!tabwin2_host_allowed()) {
    http_response_code(400);
    exit('Endereço local inválido.');
}
try {
    tabwin2_start_session();
} catch (Throwable $error) {
    http_response_code(500);
    exit('Não foi possível validar a sessão local.');
}
if (strtolower((string) ($_SERVER['HTTP_SEC_FETCH_SITE'] ?? '')) === 'cross-site') {
    session_write_close();
    http_response_code(403);
    exit('Origem da solicitação não autorizada.');
}

$token = $_GET['token'] ?? '';
if (!is_string($token) || !preg_match('/\A[a-f0-9]{32}\z/', $token)) {
    session_write_close();
    http_response_code(400);
    exit('Arquivo inválido.');
}
if (!tabwin2_download_token_allowed($token)) {
    session_write_close();
    http_response_code(403);
    exit('Este download não pertence à sessão atual. Reabra o resultado pela tela de tabulação.');
}
session_write_close();
$dataDirectory = getenv('TABWIN2_DATA_DIR') ?: (__DIR__ . DIRECTORY_SEPARATOR . 'uploads');
$root = realpath($dataDirectory);
$file = $root === false ? false : realpath($root . DIRECTORY_SEPARATOR . 'RESULTADOS' . DIRECTORY_SEPARATOR . $token . '.dbf');
if ($file === false || !str_starts_with(strtolower($file), strtolower($root . DIRECTORY_SEPARATOR . 'RESULTADOS' . DIRECTORY_SEPARATOR))) {
    http_response_code(404);
    exit('O arquivo de registros não está mais disponível.');
}
if (!is_file($file)) {
    http_response_code(404);
    exit('O arquivo de registros não está mais disponível.');
}
header('Content-Type: application/octet-stream');
header('Content-Length: ' . (string) filesize($file));
header('Content-Disposition: attachment; filename="tabulacao-' . substr($token, 0, 8) . '.dbf"');
header('Cache-Control: private, no-store');
readfile($file);
