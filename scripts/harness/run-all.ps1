param(
    [switch]$FullDocker,
    [switch]$UseDockerForTests
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Get-Command python -ErrorAction Stop

function Run-Native {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

Push-Location $root
try {
    Write-Host "GroundDesk Agent Harness 统一门禁"
    Write-Host "========================"

    Run-Native $python.Source @("scripts/harness/check_secrets.py")
    Run-Native $python.Source @("scripts/harness/check_architecture.py")
    Run-Native $python.Source @("scripts/harness/check_embedding_contract.py")

    & (Join-Path $PSScriptRoot "run-backend-tests.ps1") -UseDocker:$UseDockerForTests
    & (Join-Path $PSScriptRoot "run-frontend-tests.ps1") -UseDocker:$UseDockerForTests
    & (Join-Path $PSScriptRoot "verify-compose.ps1") -Full:$FullDocker

    Write-Host "========================"
    Write-Host "[通过] 全部 Harness 门禁"
} finally {
    Pop-Location
}
