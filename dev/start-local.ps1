param(
    [string]$PythonExecutable = (Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'),
    [string]$DatabaseServer = (Join-Path $PSScriptRoot 'pglite/node_modules/@electric-sql/pglite-socket/dist/scripts/server.js'),
    [int]$Port = 8010,
    [int]$DatabasePort = 5433
)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path $PSScriptRoot -Parent
$backendDirectory = Join-Path $projectDirectory 'backend'
$siteDirectory = Join-Path $projectDirectory 'frontend/dist'
$runtimeDirectory = Join-Path $PSScriptRoot '.local'

foreach ($requiredPath in @($PythonExecutable, $DatabaseServer, (Join-Path $siteDirectory 'index.html'))) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Missing $requiredPath. Install dependencies and build the frontend first; see docs/LOCAL_SETUP.md."
    }
}
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
$DatabaseServer = (Resolve-Path -LiteralPath $DatabaseServer).Path

function Test-LocalPort([int]$Number) {
    $connection = [System.Net.Sockets.TcpClient]::new()
    try {
        $attempt = $connection.ConnectAsync('127.0.0.1', $Number)
        return ($attempt.Wait(300) -and $connection.Connected)
    } catch {
        return $false
    } finally {
        $connection.Dispose()
    }
}

$url = "http://127.0.0.1:$Port"
if (Test-LocalPort $Port) {
    $health = Invoke-RestMethod "$url/health" -TimeoutSec 5
    if ($health.status -eq 'ok') {
        Write-Output "App is already running: $url/assistant"
        exit 0
    }
    throw "Port $Port is already in use. Choose another -Port."
}
if (Test-LocalPort $DatabasePort) {
    throw "Database port $DatabasePort is already in use. Choose another -DatabasePort to keep this preview's data separate."
}

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$databaseDirectory = Join-Path $runtimeDirectory 'database'
$database = Start-Process -FilePath (Get-Command node.exe).Source -WindowStyle Hidden -PassThru `
    -ArgumentList @("`"$DatabaseServer`"", "`"--db=$databaseDirectory`"", "--port=$DatabasePort", '--host=127.0.0.1', '--extensions=@electric-sql/pglite-pgvector:vector', '--max-connections=20') `
    -WorkingDirectory $projectDirectory `
    -RedirectStandardOutput (Join-Path $runtimeDirectory 'database.log') `
    -RedirectStandardError (Join-Path $runtimeDirectory 'database-error.log')

for ($attempt = 0; $attempt -lt 60 -and -not (Test-LocalPort $DatabasePort); $attempt++) {
    if ($database.HasExited) { throw "Database startup failed. See $runtimeDirectory/database-error.log." }
    Start-Sleep -Milliseconds 500
}
if (-not (Test-LocalPort $DatabasePort)) { throw 'The local database did not become ready.' }

$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:$DatabasePort/postgres?sslmode=disable"
$env:DB_DISABLE_PREPARED_STATEMENTS = 'true'
$env:ENVIRONMENT = 'development'
$env:COOKIE_SECURE = 'false'
$env:SINGLE_PROCESS = 'true'
$env:STATIC_DIR = $siteDirectory
$env:PYTHONDONTWRITEBYTECODE = '1'

Push-Location $backendDirectory
try {
    & $PythonExecutable -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    & $PythonExecutable -m scripts.seed_demo --incidents 50
    if ($LASTEXITCODE -ne 0) { throw 'Demo preparation failed.' }
} finally {
    Pop-Location
}

$application = Start-Process -FilePath $PythonExecutable -WindowStyle Hidden -PassThru `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port") `
    -WorkingDirectory $backendDirectory `
    -RedirectStandardOutput (Join-Path $runtimeDirectory 'app.log') `
    -RedirectStandardError (Join-Path $runtimeDirectory 'app-error.log')

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($application.HasExited) { throw "App startup failed. See $runtimeDirectory/app-error.log." }
    try {
        $response = Invoke-WebRequest "$url/ready" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            @{ app_pid = $application.Id; database_pid = $database.Id; url = $url } |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeDirectory 'processes.json')
            Write-Output "App is ready: $url/assistant"
            Write-Output "Data and logs: $runtimeDirectory"
            exit 0
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}
throw "App startup timed out. See $runtimeDirectory/app-error.log."
