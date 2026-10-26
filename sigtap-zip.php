<?php
declare(strict_types=1);
require_once __DIR__ . '/security.php';
tabwin2_security_headers();
if (!tabwin2_host_allowed()) {
    http_response_code(400);
    exit('Endereço local inválido.');
}
if (strtolower((string) ($_SERVER['HTTP_SEC_FETCH_SITE'] ?? '')) === 'cross-site') {
    http_response_code(403);
    exit('Origem da solicitação não autorizada.');
}
try {
    tabwin2_start_session();
    session_write_close();
} catch (Throwable $error) {
    http_response_code(500);
    exit('Não foi possível validar a sessão local.');
}

$filename = $_GET['arquivo'] ?? '';
if (!is_string($filename) || preg_match('/\ATabelaUnificada_20\d{4}_v\d{10,14}\.zip\z/D', $filename) !== 1) {
    http_response_code(400);
    exit('Arquivo SIGTAP inválido.');
}
$dataDirectory = getenv('TABWIN2_DATA_DIR') ?: (__DIR__ . DIRECTORY_SEPARATOR . 'uploads');
$store = realpath($dataDirectory . DIRECTORY_SEPARATOR . '.cache' . DIRECTORY_SEPARATOR . 'sigtap');
$file = $store === false ? false : realpath($store . DIRECTORY_SEPARATOR . $filename);
if ($file === false || strcasecmp(dirname($file), $store) !== 0 || !is_file($file)) {
    http_response_code(404);
    exit('Prepare o ZIP na página SIGTAP antes de baixar.');
}
header('Content-Type: application/zip');
header('Content-Length: ' . (string) filesize($file));
header('Content-Disposition: attachment; filename="' . $filename . '"');
header('Cache-Control: private, no-store');
readfile($file);
