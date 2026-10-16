<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
set_time_limit(0);
ignore_user_abort(true);
ob_start();
register_shutdown_function(static function (): void {
    $error = error_get_last();
    if ($error && in_array($error['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR, E_USER_ERROR], true)) {
        error_log('[tabwin2] ' . $error['message'] . ' in ' . $error['file'] . ':' . $error['line']);
        while (ob_get_level() > 0) {
            ob_end_clean();
        }
        if (!headers_sent()) {
            http_response_code(500);
            header('Content-Type: application/json; charset=utf-8');
        }
        echo json_encode(['ok' => false, 'error' => 'Falha interna no serviço de dados. Consulte o log do PHP.'], JSON_INVALID_UTF8_SUBSTITUTE);
    }
});

function respond(array $body, int $status = 200): never
{
    http_response_code($status);
    $json = json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
    echo $json === false ? '{"ok":false,"error":"Falha ao preparar a resposta do serviço."}' : $json;
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    respond(['ok' => false, 'error' => 'Use uma solicitação POST.'], 405);
}

$payload = json_decode(file_get_contents('php://input') ?: '', true);
if (!is_array($payload)) {
    respond(['ok' => false, 'error' => 'Não foi possível interpretar a solicitação.'], 400);
}

$action = $payload['action'] ?? '';
if (!in_array($action, ['competencies', 'files', 'download', 'catalog', 'schema', 'column_values', 'category_values', 'tabulate', 'tabulate_start', 'tabulate_status', 'convert_start', 'convert_status'], true)) {
    respond(['ok' => false, 'error' => 'Ação não reconhecida.'], 400);
}

if (in_array($action, ['catalog', 'schema', 'column_values', 'category_values', 'tabulate', 'tabulate_start', 'tabulate_status', 'convert_start', 'convert_status'], true)) {
    $payload['action'] = $action;
}

if (!in_array($action, ['catalog', 'schema', 'column_values', 'category_values', 'tabulate', 'tabulate_start', 'tabulate_status', 'convert_start', 'convert_status'], true)) {
if (!in_array($payload['system'] ?? '', ['sia', 'sih'], true)) {
    respond(['ok' => false, 'error' => 'Selecione uma base válida.'], 400);
}

$year = filter_var($payload['year'] ?? null, FILTER_VALIDATE_INT);
if ($year === false || $year < 2008 || $year > (int) date('Y')) {
    respond(['ok' => false, 'error' => 'Ano fora do intervalo disponível.'], 400);
}

if ($action !== 'competencies') {
    $month = filter_var($payload['month'] ?? null, FILTER_VALIDATE_INT);
    if ($month === false || $month < 1 || $month > 12) {
        respond(['ok' => false, 'error' => 'Competência inválida.'], 400);
    }
    $payload['month'] = $month;
}
$payload['year'] = $year;
$payload['action'] = $action;
}

$python = getenv('TABWIN2_PYTHON') ?: '';
$dataDirectory = getenv('TABWIN2_DATA_DIR') ?: (__DIR__ . DIRECTORY_SEPARATOR . 'uploads');
$dataDirectory = rtrim($dataDirectory, '\\/');
if (!is_dir($dataDirectory)) {
    @mkdir($dataDirectory, 0775, true);
}
$localAppData = getenv('LOCALAPPDATA') ?: '';
$localPython = $localAppData !== '' ? glob(rtrim($localAppData, '\\/') . '/Programs/Python/Python*/python.exe') : [];
if (!$localPython) {
    $localPython = glob('C:/Users/*/AppData/Local/Programs/Python/Python*/python.exe') ?: [];
}
if (is_array($localPython)) {
    rsort($localPython, SORT_NATURAL | SORT_FLAG_CASE);
}
$candidates = array_filter([
    $python,
    ...($localPython ?: []),
    'python',
]);
$script = __DIR__ . DIRECTORY_SEPARATOR . 'engine' . DIRECTORY_SEPARATOR . (in_array($action, ['catalog', 'schema', 'column_values', 'category_values', 'tabulate', 'tabulate_start', 'tabulate_status', 'convert_start', 'convert_status'], true) ? 'tabulation.py' : 'datasus.py');
$lastError = '';

foreach ($candidates as $binary) {
    $command = escapeshellarg($binary) . ' ' . escapeshellarg($script) . ' --json';
    $pipes = [];
    $environment = getenv();
    $environment['TABWIN2_DATA_DIR'] = $dataDirectory;
    $process = @proc_open($command, [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, __DIR__, $environment);
    if (!is_resource($process)) {
        $lastError = 'Não foi possível iniciar o serviço de busca.';
        continue;
    }

    fwrite($pipes[0], json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE));
    fclose($pipes[0]);
    $stdout = stream_get_contents($pipes[1]);
    fclose($pipes[1]);
    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[2]);
    $exitCode = proc_close($process);
    $result = json_decode($stdout ?: '', true);

    if (is_array($result)) {
        respond($result, $exitCode === 0 ? 200 : 502);
    }
    $lastError = trim($stderr) ?: 'O mecanismo de dados retornou uma resposta inválida.';
}

respond(['ok' => false, 'error' => 'Não foi possível executar o mecanismo de dados. ' . $lastError], 500);
