param(
    [ValidateSet('Frontend', 'Backend', 'Worker')]
    [string]$Service = 'Frontend',
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

function Find-Node {
    $installed = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($installed) { return $installed.Source }
    $candidates = @(
        "$env:ProgramFiles\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\nodejs\node.exe",
        "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    )
    foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    throw 'Node.js is missing. Install Node.js LTS and reopen your terminal.'
}

function Find-Python {
    $installed = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($installed -and $installed.Source -notmatch '\\WindowsApps\\') { return $installed.Source }
    foreach ($version in @('Python313', 'Python312', 'Python314', 'Python311')) {
        $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\$version\python.exe"
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw 'Python 3.11 or newer is missing. Install Python and reopen your terminal.'
}

try {
    if ($Service -eq 'Frontend') {
        Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
        $nodeRuntime = Find-Node
        $env:PATH = (Split-Path $nodeRuntime) + ';' + $env:PATH
        if ($Check) {
            & $nodeRuntime --version
            if ($LASTEXITCODE -ne 0) { throw 'Node.js could not start.' }
            if (-not (Test-Path 'node_modules\vite\bin\vite.js')) { throw 'Frontend dependencies are missing. Run start_frontend.bat to install them.' }
            Write-Host 'Frontend runtime and Vite are available.'
            exit 0
        }
        if (-not (Test-Path 'node_modules\vite\bin\vite.js')) {
            $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
            $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
            if ($npmCommand) {
                & $npmCommand.Source ci --legacy-peer-deps
            } elseif ($pnpmCommand) {
                & $pnpmCommand.Source install --ignore-scripts
            } else {
                throw 'npm or pnpm is needed to install dependencies. Install the standard Node.js LTS distribution.'
            }
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed. Review the error above.' }
        }
        & $nodeRuntime scripts/vite.mjs --host 127.0.0.1 --port 3000 --strictPort
        exit $LASTEXITCODE
    }

    Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
    $venvPython = Join-Path (Get-Location).Path 'venv\Scripts\python.exe'
    if ($Check) {
        $pythonRuntime = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { Find-Python }
        & $pythonRuntime --version
        if ($LASTEXITCODE -ne 0) { throw 'Python could not start.' }
        Write-Host 'Python is available. Backend startup creates the project virtual environment if needed.'
        exit 0
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($Service -eq 'Worker') { throw 'Run start_backend.bat first to prepare the Python environment.' }
        $pythonRuntime = Find-Python
        & $pythonRuntime -m venv venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
    }
    & $venvPython -c 'import fastapi, uvicorn, solders, dotenv, requests, nacl, base58'
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    }
    if ($Service -eq 'Backend') {
        & $venvPython -m uvicorn main:app --host 127.0.0.1 --port 8000
    } else {
        Write-Host 'Worker uses a separate Docker sandbox per task. Configure APERTURE_WORKER_TOKEN in backend/.env.'
        Write-Host 'Build the task image first: docker build -f backend/Dockerfile.sandbox -t aperture-task:local backend'
        & $venvPython -u worker.py
    }
    exit $LASTEXITCODE
} catch {
    Write-Host ('[Aperture] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
