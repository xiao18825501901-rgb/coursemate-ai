param(
    [switch]$OpenAI
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$node = (Get-Command node -ErrorAction Stop).Source
$nodeVersion = [Version]((& $node --version).TrimStart('v'))
if ($nodeVersion -lt [Version]'24.14.0') {
    throw "CourseMate requires Node.js 24.14.0 or newer; PATH resolves to $nodeVersion."
}
$python = Join-Path $repo 'services\rag-api\.venv\Scripts\python.exe'
$logDir = Join-Path $repo 'work\local-logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not $OpenAI) {
    $env:RAG_PROVIDER_MODE = 'deterministic'
    $env:AGENT_PROVIDER_MODE = 'deterministic'
}
$env:AGENT_DATABASE_PATH = Join-Path $repo 'data\agent.sqlite3'
$env:AGENT_PORT = '8001'
$env:WEB_ORIGIN = 'http://127.0.0.1:5173'
$env:VITE_RAG_API_URL = 'http://127.0.0.1:8000'
$env:VITE_AGENT_API_URL = 'http://127.0.0.1:8001'

$processes = @()
try {
    $processes += Start-Process -FilePath $python -WorkingDirectory (Join-Path $repo 'services\rag-api') -ArgumentList '-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port','8000' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'rag.out.log') -RedirectStandardError (Join-Path $logDir 'rag.err.log') -PassThru
    $processes += Start-Process -FilePath $node -WorkingDirectory $repo -ArgumentList (Join-Path $repo 'services\agent-api\dist\src\server.js') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'agent.out.log') -RedirectStandardError (Join-Path $logDir 'agent.err.log') -PassThru
    $processes += Start-Process -FilePath $node -WorkingDirectory (Join-Path $repo 'apps\web') -ArgumentList (Join-Path $repo 'node_modules\vite\bin\vite.js'),'--host','127.0.0.1' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'web.out.log') -RedirectStandardError (Join-Path $logDir 'web.err.log') -PassThru
    Write-Host 'CourseMate is starting at http://127.0.0.1:5173'
    Write-Host 'Press Ctrl+C to stop all three project processes.'
    while ($true) {
        Start-Sleep -Seconds 1
        $exited = $processes | Where-Object HasExited
        if ($exited) { throw "A CourseMate process exited early. See $logDir" }
    }
}
finally {
    foreach ($process in $processes) {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id }
    }
}
