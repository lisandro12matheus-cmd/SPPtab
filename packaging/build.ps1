param([switch]$SkipSelfTests)
$ErrorActionPreference = 'Stop'

$PackagingRoot = $PSScriptRoot
$AppRoot = Split-Path -Parent $PackagingRoot
$WorkspaceRoot = Split-Path -Parent $AppRoot
$BuildRoot = Join-Path $AppRoot '.build\portable'
$RuntimeCache = Join-Path (Split-Path -Parent $BuildRoot) 'runtime-cache'
$OutputRoot = Join-Path $AppRoot 'dist'
$PayloadRoot = Join-Path $BuildRoot 'payload'
$AppPayload = Join-Path $PayloadRoot 'App'
$PhpPayload = Join-Path $AppPayload 'runtime\php'
$PythonPayload = Join-Path $AppPayload 'runtime\python'
$AppFiles = Join-Path $AppPayload 'app'
$PythonZip = Join-Path $RuntimeCache 'python-3.14.8-embed-amd64.zip'
$PayloadZip = Join-Path $BuildRoot 'SPPtab-Payload.zip'
$PythonUrl = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-embed-amd64.zip'
$PythonSha256 = 'a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310'
$PhpZip = Join-Path $RuntimeCache 'php-8.5.11-nts-x64.zip'
$PhpUrl = 'https://downloads.php.net/~windows/releases/archives/php-8.5.11-nts-Win32-vs17-x64.zip'
$PhpSha256 = '0ea96e0d2b9b737a6036f05cf4e95c49313faa6d0f27bd97edb2742503f0c043'
$PhpExtract = Join-Path $BuildRoot 'php-extracted'
$PhpSource = $PhpExtract
$Compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$LauncherSource = Join-Path $PackagingRoot 'Launcher.cs'
$InstallerSource = Join-Path $PackagingRoot 'Installer.cs'
$RouterSource = Join-Path $PackagingRoot 'router.php'
$SetupOutput = Join-Path $OutputRoot 'SPPtab-Setup.exe'
$PortableOutput = Join-Path $OutputRoot 'SPPtab-Portable.zip'

if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) { throw 'O compilador C# do Windows não está disponível neste computador.' }

$resolvedBuild = [IO.Path]::GetFullPath($BuildRoot)
$resolvedApp = [IO.Path]::GetFullPath($AppRoot) + [IO.Path]::DirectorySeparatorChar
if (-not $resolvedBuild.StartsWith($resolvedApp, [StringComparison]::OrdinalIgnoreCase)) { throw 'A pasta temporária de empacotamento saiu da pasta do SPPtab.' }
if (Test-Path -LiteralPath $BuildRoot) { Remove-Item -LiteralPath $BuildRoot -Recurse -Force }
New-Item -ItemType Directory -Path $AppPayload, $PhpPayload, $PythonPayload, $AppFiles, $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeCache -Force | Out-Null

Write-Host 'Baixando o runtime Python portátil…'
if (-not (Test-Path -LiteralPath $PythonZip)) {
    & curl.exe --fail --location --silent --show-error --output $PythonZip $PythonUrl
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível baixar o Python portátil oficial.' }
}
$downloadedPythonHash = (Get-FileHash -LiteralPath $PythonZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($downloadedPythonHash -ne $PythonSha256) { throw 'A verificação SHA-256 do runtime Python não confere.' }
$PythonExtract = Join-Path $BuildRoot 'python-extracted'
Expand-Archive -LiteralPath $PythonZip -DestinationPath $PythonExtract -Force
Copy-Item -Path (Join-Path $PythonExtract '*') -Destination $PythonPayload -Recurse -Force
$PythonPathConfig = Get-ChildItem -LiteralPath $PythonPayload -File -Filter 'python*._pth' | Select-Object -First 1
if (-not $PythonPathConfig) { throw 'O Python portátil não contém o arquivo de configuração de módulos.' }
# O Python embutido usa _pth isolado e não inclui automaticamente a pasta do script.
# Sem este caminho, um computador sem Python instalado não encontra official_source.py.
Add-Content -LiteralPath $PythonPathConfig.FullName -Value '..\..\app\engine' -Encoding ASCII

Write-Host 'Baixando e conferindo o runtime PHP oficial…'
if (-not (Test-Path -LiteralPath $PhpZip)) {
    & curl.exe --fail --location --silent --show-error --output $PhpZip $PhpUrl
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível baixar o runtime PHP oficial.' }
}
$downloadedPhpHash = (Get-FileHash -LiteralPath $PhpZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($downloadedPhpHash -ne $PhpSha256) { throw 'A verificação SHA-256 do runtime PHP não confere.' }
Expand-Archive -LiteralPath $PhpZip -DestinationPath $PhpExtract -Force
if (-not (Test-Path -LiteralPath (Join-Path $PhpSource 'php.exe'))) { throw 'O pacote PHP oficial não contém php.exe no local esperado.' }

Write-Host 'Preparando o app e os arquivos de definição necessários…'
Get-ChildItem -LiteralPath $AppRoot -File -Filter '*.php' | Copy-Item -Destination $AppFiles
Copy-Item -LiteralPath (Join-Path $AppRoot 'assets') -Destination $AppFiles -Recurse -Force
Copy-Item -LiteralPath (Join-Path $AppRoot 'engine') -Destination $AppFiles -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $AppFiles 'packaging') -Force | Out-Null
Copy-Item -LiteralPath $RouterSource -Destination (Join-Path $AppFiles 'packaging\router.php') -Force

Get-ChildItem -LiteralPath $AppFiles -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force
}
Get-ChildItem -LiteralPath (Join-Path $AppFiles 'engine\vendor\dbfread') -File -Filter 'test_*.py' -ErrorAction SilentlyContinue | Remove-Item -Force
Remove-Item -LiteralPath (Join-Path $AppFiles 'engine\vendor\dbc_reader\bin\blast-dbf-darwin') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $AppFiles 'engine\vendor\dbc_reader\bin\blast-dbf-linux') -Force -ErrorAction SilentlyContinue

Write-Host 'Incluindo o runtime PHP e as bibliotecas Windows necessárias…'
Copy-Item -LiteralPath (Join-Path $PhpSource 'php.exe') -Destination $PhpPayload -Force
Get-ChildItem -LiteralPath $PhpSource -File -Filter '*.dll' | Copy-Item -Destination $PhpPayload -Force
Copy-Item -LiteralPath (Join-Path $PhpSource 'license.txt') -Destination (Join-Path $AppPayload 'PHP-LICENSE.txt') -Force
$runtimeNames = @('concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'vcruntime140_threads.dll')
foreach ($runtimeName in $runtimeNames) {
    $runtimeSource = Join-Path (Join-Path $env:WINDIR 'System32') $runtimeName
    if (-not (Test-Path -LiteralPath $runtimeSource)) { throw "O runtime Visual C++ necessário não está disponível: $runtimeName" }
    Copy-Item -LiteralPath $runtimeSource -Destination $PhpPayload -Force
}
@'
Os arquivos Visual C++ Runtime incluídos neste pacote são redistribuíveis da Microsoft e acompanham o PHP para evitar uma instalação separada de dependências.
'@ | Set-Content -LiteralPath (Join-Path $AppPayload 'VC-RUNTIME-NOTICE.txt') -Encoding UTF8
@'
[PHP]
engine=On
expose_php=Off
display_errors=Off
log_errors=On
max_execution_time=0
max_input_time=-1
memory_limit=2048M
post_max_size=64M
upload_max_filesize=64M
date.timezone=America/Sao_Paulo
opcache.enable=0
opcache.enable_cli=0
disable_functions=exec,shell_exec,system,passthru,popen
'@ | Set-Content -LiteralPath (Join-Path $PhpPayload 'php.ini') -Encoding ASCII

$pythonLicense = Join-Path $PythonExtract 'LICENSE.txt'
if (Test-Path -LiteralPath $pythonLicense) {
    Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $AppPayload 'PYTHON-LICENSE.txt') -Force
}
@'
SPPtab — versão portátil para Windows 64 bits

Extraia a pasta SPPtab para um local que você possa acessar, como Downloads ou Área de Trabalho. Depois, abra SPPtab.exe. Não precisa instalar PHP, Python nem servidor.

Uma janela pequena mantém o serviço local ligado e o app abre no navegador padrão. O botão X recolhe a janela para a bandeja, mantendo o sistema funcionando. Para desligar, use “Encerrar SPPtab” na janela ou no menu do ícone perto do relógio.

Em uma pasta nova, os arquivos baixados e convertidos ficam em data, ao lado de SPPtab.exe. Se você já usava outra versão, o app reaproveita a biblioteca existente. Se a pasta escolhida não permitir gravação, usa uma pasta local da sua conta. Para levar a biblioteca para outro computador, copie a pasta de dados indicada na etapa de conversão.

Para buscar bases e definições oficiais, conecte-se à internet e use a tela “Buscar arquivos”. A consulta usa HTTPS e, se necessário, tenta o FTP. Se a rede bloquear ambos, você ainda pode copiar a pasta data de outro computador e trabalhar com os arquivos já salvos.

Este pacote não possui assinatura digital; o Windows pode exibir um aviso de aplicativo não reconhecido na primeira execução. Confira a origem do download e compare o SHA-256 do ZIP com o arquivo SPPtab-Portable-SHA256SUM.txt da mesma versão antes de executá-lo.
'@ | Set-Content -LiteralPath (Join-Path $AppPayload 'LEIA-ME.txt') -Encoding UTF8

Write-Host 'Montando o executável…'
if (-not $SkipSelfTests) {
    $phpExe = Join-Path $PhpPayload 'php.exe'
    $phpTest = & $phpExe -c (Join-Path $PhpPayload 'php.ini') -r "echo PHP_VERSION . '|' . (function_exists('proc_open') ? 'proc_open-ok' : 'proc_open-falhou') . '|' . json_encode(['ok' => true]);"
    if ($LASTEXITCODE -ne 0 -or $phpTest -notmatch 'proc_open-ok' -or $phpTest -notmatch '"ok":true') { throw 'O PHP empacotado não passou pela verificação básica.' }

    $embeddedPython = Join-Path $PythonPayload 'python.exe'
    $vendorPath = Join-Path $AppFiles 'engine\vendor'
    $enginePath = Join-Path $AppFiles 'engine'
    $dataPathSmoke = Join-Path $BuildRoot 'data-path-selftest'
    $pythonSmoke = "import os, sys, ftplib, json, zipfile; os.environ['TABWIN2_DATA_DIR']=r'$dataPathSmoke'; sys.path.insert(0, r'$vendorPath'); sys.path.insert(0, r'$enginePath'); import dbfread, dbctodbf, datasus, official_source, storage_lock, tabulation; assert datasus.library_folder('sia', 2026, 7) == 'uploads/SIA/2026/07'; print('python-ok')"
    $pythonTest = & $embeddedPython -c $pythonSmoke
    if ($LASTEXITCODE -ne 0 -or $pythonTest -notmatch 'python-ok') { throw 'O Python portátil ou as bibliotecas DBF não passaram pela verificação.' }
}

$launcherExe = Join-Path $AppPayload 'SPPtab.exe'
$launcherArgs = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+', ('/out:' + $launcherExe), '/reference:System.dll', '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', $LauncherSource)
& $Compiler @launcherArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $launcherExe)) { throw 'Não foi possível compilar o iniciador do SPPtab.' }

if (-not $SkipSelfTests) {
    & $launcherExe --self-test
    if ($LASTEXITCODE -ne 0) {
        $selfTestLog = Join-Path $env:TEMP 'TabWin2-selftest.log'
        if (Test-Path -LiteralPath $selfTestLog) { Get-Content -LiteralPath $selfTestLog }
        throw 'A verificação local do app falhou; consulte a mensagem acima.'
    }
    $selfTestLog = Join-Path $env:TEMP 'TabWin2-selftest.log'
    if (Test-Path -LiteralPath $selfTestLog) { Get-Content -LiteralPath $selfTestLog; Remove-Item -LiteralPath $selfTestLog -Force }
}

if (Test-Path -LiteralPath $PayloadZip) { Remove-Item -LiteralPath $PayloadZip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($PayloadZip, [IO.Compression.ZipArchiveMode]::Create)
try {
    $basePrefix = [IO.Path]::GetFullPath($AppPayload).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $payloadFiles = Get-ChildItem -LiteralPath $AppPayload -File -Recurse -Force | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' }
    foreach ($payloadFile in $payloadFiles) {
        $entryName = $payloadFile.FullName.Substring($basePrefix.Length).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $payloadFile.FullName, $entryName, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
}
finally {
    $archive.Dispose()
}
$requiredEntries = @('SPPtab.exe', 'runtime/php/php.exe', 'runtime/php/php.ini', 'runtime/python/python.exe', 'app/api.php', 'app/security.php', 'app/engine/storage_lock.py', 'app/bases.php', 'app/tabular.php', 'app/pacotes.php', 'app/minhas-tabulacoes.php', 'app/assets/presets.css', 'app/assets/saved-tabulations.js', 'app/assets/tabulations-nav.js', 'app/packaging/router.php')
$archiveCheck = [IO.Compression.ZipFile]::OpenRead($PayloadZip)
try {
    $actualEntries = @($archiveCheck.Entries | ForEach-Object { $_.FullName })
    foreach ($entry in $requiredEntries) {
        if ($actualEntries -notcontains $entry) { throw "O pacote não contém o componente obrigatório: $entry" }
    }
}
finally {
    $archiveCheck.Dispose()
}

if (Test-Path -LiteralPath $PortableOutput) { Remove-Item -LiteralPath $PortableOutput -Force }
$portableArchive = [IO.Compression.ZipFile]::Open($PortableOutput, [IO.Compression.ZipArchiveMode]::Create)
try {
    $portablePrefix = [IO.Path]::GetFullPath($AppPayload).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $portableFiles = Get-ChildItem -LiteralPath $AppPayload -File -Recurse -Force | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' }
    foreach ($portableFile in $portableFiles) {
    $entryName = 'SPPtab/' + $portableFile.FullName.Substring($portablePrefix.Length).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($portableArchive, $portableFile.FullName, $entryName, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
}
finally {
    $portableArchive.Dispose()
}
$portableCheck = [IO.Compression.ZipFile]::OpenRead($PortableOutput)
try {
    $portableEntries = @($portableCheck.Entries | ForEach-Object { $_.FullName })
    foreach ($entry in @('SPPtab/SPPtab.exe', 'SPPtab/runtime/php/php.exe', 'SPPtab/runtime/python/python.exe', 'SPPtab/app/index.php', 'SPPtab/app/security.php', 'SPPtab/app/engine/storage_lock.py', 'SPPtab/app/bases.php', 'SPPtab/app/tabular.php', 'SPPtab/app/pacotes.php', 'SPPtab/app/minhas-tabulacoes.php', 'SPPtab/app/assets/app.css', 'SPPtab/app/assets/presets.css', 'SPPtab/app/assets/saved-tabulations.js', 'SPPtab/app/assets/tabulations-nav.js', 'SPPtab/LEIA-ME.txt')) {
        if ($portableEntries -notcontains $entry) { throw "A pasta portátil não contém o componente obrigatório: $entry" }
    }
}
finally {
    $portableCheck.Dispose()
}

$installerArgs = @(
    '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
    ('/out:' + $SetupOutput),
    '/reference:System.dll', '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
    '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
    ('/resource:' + $PayloadZip + ',SPPtab.Payload.zip'),
    $InstallerSource
)
& $Compiler @installerArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $SetupOutput)) { throw 'Não foi possível gerar o instalador do SPPtab.' }

if (-not $SkipSelfTests) {
    $installerTest = New-Object System.Diagnostics.Process
    $installerTest.StartInfo.FileName = $SetupOutput
    $installerTest.StartInfo.Arguments = '--self-test-package'
    $installerTest.StartInfo.UseShellExecute = $false
    $installerTest.StartInfo.CreateNoWindow = $true
    if (-not $installerTest.Start()) { throw 'Não foi possível executar a verificação do instalador.' }
    if (-not $installerTest.WaitForExit(60000)) {
        $installerTest.Kill()
        throw 'A verificação do instalador excedeu 60 segundos.'
    }
    $installerExitCode = $installerTest.ExitCode
    $installerTest.Dispose()
    $installerTestLog = Join-Path $env:TEMP 'TabWin2-installer-selftest.log'
    if ($installerExitCode -ne 0) {
        if (Test-Path -LiteralPath $installerTestLog) { Get-Content -LiteralPath $installerTestLog }
        throw 'O instalador não passou pela verificação de extração e inicialização.'
    }
    if (-not (Test-Path -LiteralPath $installerTestLog)) { throw 'O instalador não deixou o resultado da sua verificação.' }
    $installerTestResult = Get-Content -LiteralPath $installerTestLog -Raw
    if ($installerTestResult -notmatch 'instalador abriu, extraiu os arquivos') { throw 'O executável não testou a extração do pacote: ' + $installerTestResult }
    Write-Host $installerTestResult.Trim()
    Remove-Item -LiteralPath $installerTestLog -Force
}

$file = Get-Item -LiteralPath $SetupOutput
$hash = (Get-FileHash -LiteralPath $SetupOutput -Algorithm SHA256).Hash
Set-Content -LiteralPath (Join-Path $OutputRoot 'SHA256SUM.txt') -Value ($hash + '  ' + $file.Name) -Encoding ASCII
Write-Host ("Instalador pronto: {0} ({1:N1} MB)" -f $SetupOutput, ($file.Length / 1MB))
Write-Host ("SHA-256: {0}" -f $hash)
$portableFile = Get-Item -LiteralPath $PortableOutput
$portableHash = (Get-FileHash -LiteralPath $PortableOutput -Algorithm SHA256).Hash
Set-Content -LiteralPath (Join-Path $OutputRoot 'SPPtab-Portable-SHA256SUM.txt') -Value ($portableHash + '  ' + $portableFile.Name) -Encoding ASCII
Write-Host ("Pasta portátil pronta: {0} ({1:N1} MB)" -f $PortableOutput, ($portableFile.Length / 1MB))
Write-Host ("SHA-256 portátil: {0}" -f $portableHash)
