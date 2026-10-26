# Smoke test do pacote portatil num Windows limpo (sem Python, Node ou VC++ instalados).
# O CI roda este script dentro de um container windows/server; tambem roda em qualquer Windows:
#   powershell -ExecutionPolicy Bypass -File scripts\smoke_test_portable.ps1 -ZipPath dist\AutoSend-Portable.zip
# Compativel com o Windows PowerShell 5.1 da imagem windows/server. Argumentos para programas nativos
# sem aspas duplas: o PowerShell 5.1 as remove (print("ok") chegava ao Python como print(ok)).
param(
    [Parameter(Mandatory = $true)][string]$ZipPath,
    [string]$WorkDir = "$env:TEMP\autosend-smoke",
    [int]$StartupTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$failures = New-Object System.Collections.Generic.List[string]

function Check([string]$Name, [scriptblock]$Test) {
    try {
        $detail = & $Test
        Write-Host "[PASS] $Name $detail"
    } catch {
        Write-Host "[FAIL] $Name -> $($_.Exception.Message)"
        $failures.Add($Name)
    }
}

# Le a tabela de imports de um PE (exe/dll) sem depender de dumpbin, que nao existe numa maquina limpa.
function Get-PeImports([string]$Path) {
    $b = [IO.File]::ReadAllBytes($Path)
    $pe = [BitConverter]::ToInt32($b, 0x3C)
    $sections = [BitConverter]::ToUInt16($b, $pe + 6)
    $optHeader = $pe + 24
    $sectionTable = $optHeader + [BitConverter]::ToUInt16($b, $pe + 20)
    $dataDirs = if ([BitConverter]::ToUInt16($b, $optHeader) -eq 0x20b) { $optHeader + 112 } else { $optHeader + 96 }
    $toOffset = {
        param($rva)
        for ($i = 0; $i -lt $sections; $i++) {
            $s = $sectionTable + 40 * $i
            $va = [BitConverter]::ToUInt32($b, $s + 12)
            $size = [Math]::Max([BitConverter]::ToUInt32($b, $s + 8), [BitConverter]::ToUInt32($b, $s + 16))
            if ($rva -ge $va -and $rva -lt $va + $size) { return $rva - $va + [BitConverter]::ToUInt32($b, $s + 20) }
        }
    }
    $names = @()
    $importRva = [BitConverter]::ToUInt32($b, $dataDirs + 8)
    if ($importRva -eq 0) { return $names }
    $desc = & $toOffset $importRva
    while ($true) {
        $nameRva = [BitConverter]::ToUInt32($b, $desc + 12)
        if ($nameRva -eq 0) { break }
        $start = & $toOffset $nameRva
        $end = $start
        while ($b[$end] -ne 0) { $end++ }
        $names += [Text.Encoding]::ASCII.GetString($b, $start, $end - $start)
        $desc += 20
    }
    $names
}

# DLLs que o binario (e as DLLs que vem junto com ele) pedem e que nao estao nem na pasta dele nem no System32.
function Get-MissingDlls([string]$Exe) {
    $dir = Split-Path $Exe
    $system = Join-Path $env:WINDIR 'System32'
    $missing = @{}
    $seen = @{}
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($Exe)
    while ($queue.Count -gt 0) {
        $file = $queue.Dequeue()
        foreach ($dll in Get-PeImports $file) {
            $key = $dll.ToLower()
            # api-ms-win-* e ext-ms-* sao API sets virtuais resolvidos pelo loader, nao arquivos.
            if ($seen.ContainsKey($key) -or $key -match '^(api|ext)-ms-') { continue }
            $seen[$key] = $true
            $local = Join-Path $dir $dll
            if (Test-Path $local) { $queue.Enqueue($local) }
            elseif (-not (Test-Path (Join-Path $system $dll))) { $missing[$dll] = (Split-Path $file -Leaf) }
        }
    }
    $missing.GetEnumerator() | ForEach-Object { "$($_.Key) (pedida por $($_.Value))" }
}

function Assert-ExitZero([string]$Exe, [string[]]$Arguments) {
    # No PowerShell 5.1, com Stop, a primeira linha de stderr de um programa nativo vira excecao e corta o resto.
    $ErrorActionPreference = 'Continue'
    $output = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" } | Out-String
    if ($LASTEXITCODE -eq -1073741515) {
        # 0xC0000135 STATUS_DLL_NOT_FOUND: falta uma DLL que so existe em maquina de desenvolvedor.
        throw "DLL ausente (0xC0000135): $((Get-MissingDlls $Exe) -join ', ')"
    }
    if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE`n$output" }
    "($(($output -split "`n")[0].Trim()))"
}

if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }
Expand-Archive -Path $ZipPath -DestinationPath $WorkDir
$root = Join-Path $WorkDir 'AutoSend-Portable'
Write-Host "Pacote extraido em $root"

foreach ($python in @('python', 'node')) {
    if (Get-Command $python -ErrorAction SilentlyContinue) {
        Write-Host "[AVISO] '$python' existe no PATH; este ambiente nao e limpo e pode esconder dependencias faltando."
    }
}

$expected = @(
    'Iniciar-AutoSend.bat',
    'app\static\index.html',
    'app\backend\src\presentation\main.py',
    'python\python.exe',
    'bin\telegram-bot-api.exe',
    'bin\ffmpeg.exe',
    'bin\ffprobe.exe'
)
foreach ($file in $expected) {
    Check "arquivo $file" { if (-not (Test-Path (Join-Path $root $file))) { throw 'ausente' } }
}

$pythonExe = Join-Path $root 'python\python.exe'
Check 'Python embutido importa as dependencias do backend' {
    Assert-ExitZero $pythonExe @('-c', 'import fastapi, uvicorn, sqlalchemy, aiosqlite, httpx, apscheduler')
}
Check 'telegram-bot-api.exe abre' { Assert-ExitZero (Join-Path $root 'bin\telegram-bot-api.exe') @('--version') }
function Test-TcpPort([System.Net.IPAddress]$Address, [int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient($Address.AddressFamily)
    try { return $client.ConnectAsync($Address, $Port).Wait(2000) } catch { return $false } finally { $client.Close() }
}

# Issue #37: o backend sobe o servidor local com --http-ip-address=127.0.0.1. Credenciais falsas bastam
# para ele abrir a porta; a checagem prova que esta versao aceita a opcao e nao escuta no IP da rede.
Check 'telegram-bot-api.exe escuta so em 127.0.0.1' {
    $tgPort = 8091
    $tgDir = Join-Path $WorkDir 'tg-smoke'
    New-Item -ItemType Directory -Path $tgDir -Force | Out-Null
    $tg = Start-Process -FilePath (Join-Path $root 'bin\telegram-bot-api.exe') -PassThru -WindowStyle Hidden `
        -ArgumentList '--local', '--http-ip-address=127.0.0.1', "--http-port=$tgPort", "--dir=$tgDir",
            '--api-id=1', '--api-hash=00000000000000000000000000000000'
    try {
        $up = $false
        for ($i = 0; $i -lt 15 -and -not $tg.HasExited; $i++) {
            if (Test-TcpPort ([System.Net.IPAddress]::Loopback) $tgPort) { $up = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $up) { throw "nao abriu a porta $tgPort em 127.0.0.1 (encerrou: $($tg.HasExited))" }
        $lan = [System.Net.Dns]::GetHostAddresses($env:COMPUTERNAME) |
            Where-Object { $_.AddressFamily -eq 'InterNetwork' -and -not [System.Net.IPAddress]::IsLoopback($_) }
        if (-not $lan) { return '(sem IPv4 de rede para conferir o lado de fora)' }
        $open = @($lan | Where-Object { Test-TcpPort $_ $tgPort })
        if ($open) { throw "porta $tgPort aberta em $($open -join ', ')" }
        "(fechada em $($lan -join ', '))"
    } finally {
        if (-not $tg.HasExited) { Stop-Process -Id $tg.Id -Force }
    }
}

Check 'ffmpeg.exe abre' { Assert-ExitZero (Join-Path $root 'bin\ffmpeg.exe') @('-version') }
Check 'ffprobe.exe abre' { Assert-ExitZero (Join-Path $root 'bin\ffprobe.exe') @('-version') }

Check 'frontend exportado nao fixa a porta 8000' {
    # Issue #65: a tela chama a API na mesma origem, porque o backend sobe na primeira porta livre de 8000 a 8020.
    $fixed = Get-ChildItem (Join-Path $root 'app\static') -Recurse -Include *.js, *.html |
        Select-String -SimpleMatch 'localhost:8000' -List
    if ($fixed) { throw "porta fixa em: $(($fixed | ForEach-Object { $_.Path }) -join ', ')" }
}

# Porta 8000 ocupada, como num PC com outro programa nela: o launcher precisa subir em outra porta.
$blocker = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 8000)
$blocker.Start()

# Issue #24: simula um banco da v0.4.0 em data\autosend.db e confere que o launcher o importa para
# %LOCALAPPDATA%\Auto-Send\autosend.db sem apagar o original.
$localAppData = Join-Path $WorkDir 'localappdata'
New-Item -ItemType Directory -Path $localAppData -Force | Out-Null
$env:LOCALAPPDATA = $localAppData
$legacyDb = Join-Path $root 'data\autosend.db'
& $pythonExe -c "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute('CREATE TABLE profiles (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, bot_token VARCHAR NOT NULL, bot_username VARCHAR NOT NULL)'); c.execute('INSERT INTO profiles VALUES (\x27p-v040\x27, \x27Acme\x27, \x27123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef\x27, \x27acme_bot\x27)'); c.commit(); c.close()" $legacyDb

# O launcher termina com "pause": a entrada vem de NUL para ele nao ficar esperando tecla.
$log = Join-Path $WorkDir 'launcher.log'
$launcher = Start-Process -FilePath 'cmd.exe' -WorkingDirectory $root -PassThru -WindowStyle Hidden `
    -ArgumentList '/c', "Iniciar-AutoSend.bat < NUL > `"$log`" 2>&1"

$base = $null
$healthy = $false
$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
while ((Get-Date) -lt $deadline -and -not $launcher.HasExited) {
    foreach ($port in 8001..8020) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health" -TimeoutSec 2
            if ($health.status -eq 'healthy') { $base = "http://127.0.0.1:$port"; $healthy = $true; break }
        } catch { }
    }
    if ($healthy) { break }
    Start-Sleep -Seconds 2
}

Check "launcher sobe o backend em ate $StartupTimeoutSeconds s com a porta 8000 ocupada" {
    if (-not $healthy) { throw 'o /api/v1/health nao respondeu em 8001-8020' }
    "($base)"
}
if ($healthy) {
    Check 'frontend estatico e servido em /' {
        $page = Invoke-WebRequest -Uri "$base/" -UseBasicParsing -TimeoutSec 10
        if ($page.StatusCode -ne 200 -or $page.Content -notmatch '<html') { throw "status $($page.StatusCode)" }
    }
    Check 'autoverificacao do launcher deu OK' {
        $report = Join-Path $root 'data\diagnostico.txt'
        if (-not (Test-Path $report)) { throw 'data\diagnostico.txt nao foi gerado' }
        $text = Get-Content $report -Raw
        if ($text -notmatch 'RESULTADO: OK') { throw "`n$text" }
    }
    # Cadastrar bot valida o token no Telegram. Um token falso tem de chegar ao Telegram e voltar recusado (422);
    # erro de conexao (400) significa backend apontando para um servidor local que nao subiu (bug da v0.2.0).
    # Depende de internet no container.
    Check 'cadastro de bot chega ao Telegram' {
        $body = '{"name":"smoke","bot_token":"123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}'
        try {
            Invoke-RestMethod -Method Post -Uri "$base/api/v1/profiles" -ContentType 'application/json' -Body $body -TimeoutSec 30 | Out-Null
        } catch [System.Net.WebException] {
            $resp = $_.Exception.Response
            if ($null -eq $resp) { throw "sem resposta HTTP: $($_.Exception.Message)" }
            $code = [int]$resp.StatusCode
            # No PowerShell 5.1 o corpo ja foi lido pelo Invoke-RestMethod e fica em ErrorDetails.
            $text = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd() }
            if ($code -eq 422 -and $text -match 'validation failed') { return "(Telegram recusou o token falso: $code)" }
            throw "status $code`n$text"
        }
        throw 'o token falso foi aceito'
    }
    Check 'API lista perfis num banco novo' {
        $profiles = Invoke-RestMethod -Uri "$base/api/v1/profiles" -TimeoutSec 10
        if (@($profiles).Count -lt 1 -or $profiles[0].name -ne 'Acme') {
            throw "perfil da v0.4.0 nao foi importado: $($profiles | ConvertTo-Json -Compress)"
        }
        if (-not (Test-Path (Join-Path $localAppData 'Auto-Send\autosend.db'))) {
            throw 'autosend.db nao foi criado em LOCALAPPDATA\Auto-Send'
        }
        if (-not (Test-Path $legacyDb)) {
            throw 'data\autosend.db original foi apagado'
        }
        "($(@($profiles).Count) perfis; importado para LOCALAPPDATA\Auto-Send)"
    }
}

$blocker.Stop()

# O launcher pode ja ter terminado (ex.: sem Python); um taskkill sem alvo nao e falha do teste.
if (-not $launcher.HasExited) { cmd.exe /c "taskkill /PID $($launcher.Id) /T /F >NUL 2>&1" }

if ($failures.Count -gt 0) {
    Write-Host "`n===== launcher.log ====="
    if (Test-Path $log) { Get-Content $log -Tail 80 }
    Write-Host "`n$($failures.Count) verificacao(oes) falharam: $($failures -join '; ')"
    exit 1
}
Write-Host "`nSmoke test do pacote portatil passou."
