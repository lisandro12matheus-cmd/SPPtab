<?php
declare(strict_types=1);

$token = $_GET['token'] ?? '';
if (!is_string($token) || !preg_match('/\A[a-f0-9]{32}\z/', $token)) {
    http_response_code(400);
    exit('Arquivo inválido.');
}
$dataDirectory = getenv('TABWIN2_DATA_DIR') ?: (__DIR__ . DIRECTORY_SEPARATOR . 'uploads');
$file = rtrim($dataDirectory, '\\/') . DIRECTORY_SEPARATOR . 'RESULTADOS' . DIRECTORY_SEPARATOR . $token . '.dbf';
if (!is_file($file)) {
    http_response_code(404);
    exit('O arquivo de registros não está mais disponível.');
}
header('Content-Type: application/octet-stream');
header('Content-Length: ' . (string) filesize($file));
header('Content-Disposition: attachment; filename="tabulacao-' . substr($token, 0, 8) . '.dbf"');
header('Cache-Control: private, no-store');
readfile($file);
