param(
    [switch]$UseDocker
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$web = Join-Path $root "web"

function Run-Native {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

$nodeVersion = if (Get-Command node -ErrorAction SilentlyContinue) {
    [version]((node --version).TrimStart("v"))
} else {
    [version]"0.0.0"
}

if (-not $UseDocker -and $nodeVersion -ge [version]"20.19.0") {
    Push-Location $web
    try {
        if (-not (Test-Path "node_modules")) { Run-Native "npm" @("ci", "--ignore-scripts") }
        Run-Native "npm" @("test")
    } finally {
        Pop-Location
    }
} else {
    $mount = "type=bind,source=$web,target=/app,readonly"
    Run-Native "docker" @(
        "run", "--rm",
        "--mount", $mount,
        "--mount", "type=volume,target=/app/node_modules",
        "-w", "/app",
        "node:22-alpine",
        "sh", "-lc",
        "npm ci --ignore-scripts && npm test"
    )
}

Write-Host "[通过] 前端测试"
