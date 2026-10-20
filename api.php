<?php
declare(strict_types=1);

require_once __DIR__ . '/security.php';
tabwin2_security_headers();
header('Content-Type: application/json; charset=utf-8');

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

try {
    $rawBody = tabwin2_api_guard();
} catch (Throwable $error) {
    $status = http_response_code();
    respond(['ok' => false, 'error' => $error->getMessage()], is_int($status) && $status >= 400 ? $status : 400);
}
$decoded = json_decode($rawBody);
if (!$decoded instanceof stdClass) {
    respond(['ok' => false, 'error' => 'A solicitação precisa ser um objeto JSON válido.'], 400);
}
$payload = json_decode($rawBody, true);
if (!is_array($payload)) {
    respond(['ok' => false, 'error' => 'A solicitação precisa ser um objeto JSON válido.'], 400);
}
set_time_limit(0);
ignore_user_abort(true);
ob_start();
register_shutdown_function(static function (): void {
    $error = error_get_last();
    if ($error && in_array($error['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR, E_USER_ERROR], true)) {
        error_log('[spptab] Falha interna no mecanismo de dados; consulte o log local protegido.');
        while (ob_get_level() > 0) ob_end_clean();
        if (!headers_sent()) {
            http_response_code(500);
            header('Content-Type: application/json; charset=utf-8');
        }
        echo json_encode(['ok' => false, 'error' => 'Falha interna no serviço de dados. Consulte o log local.'], JSON_INVALID_UTF8_SUBSTITUTE);
    }
});

$action = $payload['action'] ?? '';
$tabulationActions = ['catalog', 'delete_file', 'schema', 'preset_list', 'preset_save', 'preset_get', 'preset_delete', 'column_values', 'category_values', 'tabulate', 'tabulate_start', 'tabulate_status', 'convert_start', 'convert_status'];
$dataActions = ['competencies', 'files', 'download', 'municipalities'];
if (!in_array($action, [...$dataActions, ...$tabulationActions], true)) {
    respond(['ok' => false, 'error' => 'Ação não reconhecida.'], 400);
}

try {
    tabwin2_validate_api_payload($payload);
} catch (Throwable $error) {
    $status = http_response_code();
    respond(['ok' => false, 'error' => $error->getMessage()], is_int($status) && $status >= 400 ? $status : 400);
}

if (in_array($action, $tabulationActions, true)) {
    $payload['action'] = $action;
} elseif ($action === 'municipalities') {
    $uf = strtoupper((string) ($payload['uf'] ?? ''));
    if (!in_array($uf, ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'], true)) {
        respond(['ok' => false, 'error' => 'Selecione uma unidade da Federação válida.'], 400);
    }
    $payload['uf'] = $uf;
} else {
    if (!in_array($payload['system'] ?? '', ['sia', 'sih'], true)) {
        respond(['ok' => false, 'error' => 'Selecione uma base válida.'], 400);
    }
    $uf = strtoupper((string) ($payload['uf'] ?? ''));
    if (!in_array($uf, ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'], true)) {
        respond(['ok' => false, 'error' => 'Selecione uma unidade da Federação válida.'], 400);
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
    $payload['uf'] = $uf;
    $payload['year'] = $year;
    $payload['action'] = $action;
}

$python = getenv('TABWIN2_PYTHON') ?: '';
$dataDirectory = getenv('TABWIN2_DATA_DIR') ?: (__DIR__ . DIRECTORY_SEPARATOR . 'uploads');
$dataDirectory = rtrim($dataDirectory, '\\/');
if (!is_dir($dataDirectory)) {
    @mkdir($dataDirectory, 0775, true);
}
$binary = $python;
if ($binary === '') {
    $localPythonConfig = $dataDirectory . DIRECTORY_SEPARATOR . '.config' . DIRECTORY_SEPARATOR . 'python-path.txt';
    if (is_file($localPythonConfig)) {
        $configuredPath = trim((string) @file_get_contents($localPythonConfig));
        if ($configuredPath !== '') $binary = $configuredPath;
    }
}
if ($binary === '' || !is_file($binary)) {
    respond(['ok' => false, 'error' => 'O Python do SPPtab não foi configurado. Informe o caminho confiável em TABWIN2_PYTHON ou no arquivo local uploads/.config/python-path.txt.'], 503);
}
$engine = in_array($action, $tabulationActions, true) ? 'tabulation.py' : 'datasus.py';
$script = __DIR__ . DIRECTORY_SEPARATOR . 'engine' . DIRECTORY_SEPARATOR . $engine;
$stdoutPath = tempnam(sys_get_temp_dir(), 'spptab-out-');
$stderrPath = tempnam(sys_get_temp_dir(), 'spptab-err-');
if ($stdoutPath === false || $stderrPath === false) {
    if (is_string($stdoutPath)) @unlink($stdoutPath);
    if (is_string($stderrPath)) @unlink($stderrPath);
    respond(['ok' => false, 'error' => 'Não foi possível preparar a execução do mecanismo de dados.'], 500);
}
$environment = getenv();
if (!is_array($environment)) $environment = [];
$environment['TABWIN2_DATA_DIR'] = $dataDirectory;
$command = [$binary, $script, '--json'];
$pipes = [];
$process = @proc_open($command, [0 => ['pipe', 'r'], 1 => ['file', $stdoutPath, 'w'], 2 => ['file', $stderrPath, 'w']], $pipes, __DIR__, $environment);
if (!is_resource($process)) {
    @unlink($stdoutPath);
    @unlink($stderrPath);
    respond(['ok' => false, 'error' => 'Não foi possível iniciar o mecanismo de dados configurado.'], 500);
}
fwrite($pipes[0], json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE));
fclose($pipes[0]);
$timeout = $action === 'download' ? 1800 : (in_array($action, ['schema', 'category_values', 'column_values', 'tabulate'], true) ? 600 : 180);
$startedAt = microtime(true);
$status = proc_get_status($process);
$tooMuchOutput = false;
while ($status['running']) {
    clearstatcache(true, $stdoutPath);
    clearstatcache(true, $stderrPath);
    if ((int) @filesize($stdoutPath) > 67108864 || (int) @filesize($stderrPath) > 2097152) {
        $tooMuchOutput = true;
        proc_terminate($process, 9);
        break;
    }
    if (microtime(true) - $startedAt > $timeout) {
        proc_terminate($process, 9);
        break;
    }
    usleep(50000);
    $status = proc_get_status($process);
}
$observedExitCode = is_array($status) ? (int) ($status['exitcode'] ?? -1) : -1;
$closedExitCode = proc_close($process);
$exitCode = $observedExitCode >= 0 ? $observedExitCode : $closedExitCode;
$stdout = (string) @file_get_contents($stdoutPath);
$stderr = (string) @file_get_contents($stderrPath, false, null, 0, 8192);
@unlink($stdoutPath);
@unlink($stderrPath);
if ($tooMuchOutput) respond(['ok' => false, 'error' => 'O mecanismo de dados excedeu o limite de resposta.'], 502);
if (microtime(true) - $startedAt > $timeout) respond(['ok' => false, 'error' => 'O mecanismo de dados excedeu o tempo permitido para esta etapa.'], 504);
$result = json_decode($stdout, true);
if (is_array($result)) {
    tabwin2_register_download_tokens($result);
    respond($result, $exitCode === 0 ? 200 : 502);
}
$diagnosticId = bin2hex(random_bytes(6));
$logDirectory = rtrim($dataDirectory, '\\/') . DIRECTORY_SEPARATOR . '.logs';
if (!is_dir($logDirectory)) @mkdir($logDirectory, 0700, true);
if (is_dir($logDirectory)) {
    @file_put_contents($logDirectory . DIRECTORY_SEPARATOR . 'engine-errors.log', '[' . date(DATE_ATOM) . '] ' . $diagnosticId . ' ' . str_replace(["\r", "\n"], ' ', $stderr) . PHP_EOL, FILE_APPEND | LOCK_EX);
}
respond(['ok' => false, 'error' => 'Não foi possível executar o mecanismo de dados. Referência local: ' . $diagnosticId . '.'], 500);
