param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Run-Compose {
    param([string[]]$Arguments)
    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE"
    }
}

Push-Location $root
try {
    Run-Compose @("config", "--quiet")

    if ($Full) {
        Run-Compose @("up", "--build", "-d")
        $deadline = (Get-Date).AddMinutes(3)
        do {
            $ids = @(& docker compose ps -q)
            $states = @()
            foreach ($id in $ids) {
                $states += (& docker inspect $id --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}")
            }
            $ready = $ids.Count -eq 4 -and ($states | Where-Object { $_ -notin @("healthy", "running") }).Count -eq 0
            if (-not $ready) { Start-Sleep -Seconds 3 }
        } while (-not $ready -and (Get-Date) -lt $deadline)

        if (-not $ready) {
            Run-Compose @("ps")
            throw "Compose services did not become healthy within 3 minutes"
        }

        $apiStatus = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/health" -TimeoutSec 10).StatusCode
        $webStatus = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:3000" -TimeoutSec 10).StatusCode
        if ($apiStatus -ne 200 -or $webStatus -ne 200) {
            throw "HTTP smoke test failed: api=$apiStatus web=$webStatus"
        }
        Write-Host "[通过] Compose 构建与健康检查"
    } else {
        Write-Host "[通过] Compose 配置检查（使用 -Full 执行构建与健康检查）"
    }
} finally {
    Pop-Location
}
