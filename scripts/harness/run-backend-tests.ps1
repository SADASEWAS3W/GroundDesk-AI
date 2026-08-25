param(
    [switch]$UseDocker
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Run-Native {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not $UseDocker -and $uv) {
    Push-Location $root
    try { Run-Native "uv" @("run", "pytest", "tests", "-q") } finally { Pop-Location }
} elseif (-not $UseDocker -and (Test-Path $venvPython)) {
    Push-Location $root
    try { Run-Native $venvPython @("-m", "pytest", "tests", "-q") } finally { Pop-Location }
} else {
    $mount = "type=bind,source=$root,target=/app,readonly"
    Run-Native "docker" @(
        "run", "--rm",
        "--mount", $mount,
        "-w", "/app",
        "-e", "UV_PROJECT_ENVIRONMENT=/tmp/grounddesk-venv",
        "python:3.12-slim",
        "sh", "-lc",
        "pip install --disable-pip-version-check uv && uv sync --frozen --extra dev && uv run pytest tests -q"
    )
}

Write-Host "[通过] 后端测试"
