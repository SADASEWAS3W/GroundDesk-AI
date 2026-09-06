#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"

full_docker=false
use_docker_for_tests=false

usage() {
    cat <<'EOF'
Usage: scripts/harness/run-all.sh [options]

Run the GroundDesk AI repository quality gates on Linux.

Options:
  --full-docker           Build and start all Compose services, wait for health,
                          and run API/Web HTTP smoke tests.
  --use-docker-for-tests  Run backend and frontend tests in temporary containers.
  -h, --help              Show this help message.
EOF
}

fail() {
    echo "[失败] $*" >&2
    exit 1
}

while (($# > 0)); do
    case "$1" in
        --full-docker)
            full_docker=true
            ;;
        --use-docker-for-tests)
            use_docker_for_tests=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "未知参数：$1"
            ;;
    esac
    shift
done

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "缺少必需命令：$1"
}

run_python_gate() {
    local script="$1"
    if command -v python >/dev/null 2>&1; then
        python "$script"
    elif command -v python3 >/dev/null 2>&1; then
        python3 "$script"
    else
        fail "缺少 python 或 python3，无法执行静态门禁"
    fi
}

run_backend_tests() {
    if [[ "$use_docker_for_tests" == false ]] && command -v uv >/dev/null 2>&1; then
        (cd "$repo_root" && uv run pytest tests -q)
    elif [[ "$use_docker_for_tests" == false && -x "$repo_root/.venv/bin/python" ]]; then
        (cd "$repo_root" && .venv/bin/python -m pytest tests -q)
    else
        require_command docker
        docker run --rm \
            --mount "type=bind,source=${repo_root},target=/app,readonly" \
            -w /app \
            -e UV_PROJECT_ENVIRONMENT=/tmp/grounddesk-venv \
            python:3.12-slim \
            sh -lc "pip install --disable-pip-version-check uv && uv sync --frozen --extra dev && uv run pytest tests -q"
    fi
    echo "[通过] 后端测试"
}

node_is_supported() {
    command -v node >/dev/null 2>&1 || return 1
    node -e '
        const [major, minor] = process.versions.node.split(".").map(Number);
        process.exit(major > 20 || (major === 20 && minor >= 19) ? 0 : 1);
    '
}

run_frontend_tests() {
    local web_root="$repo_root/web"
    if [[ "$use_docker_for_tests" == false ]] && node_is_supported; then
        require_command npm
        (
            cd "$web_root"
            if [[ ! -d node_modules ]]; then
                npm ci --ignore-scripts
            fi
            npm test
        )
    else
        require_command docker
        docker run --rm \
            --mount "type=bind,source=${web_root},target=/app,readonly" \
            --mount "type=volume,target=/app/node_modules" \
            -w /app \
            node:22-alpine \
            sh -lc "npm ci --ignore-scripts && npm test"
    fi
    echo "[通过] 前端测试"
}

compose_service_state() {
    local container_id="$1"
    docker inspect "$container_id" \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}'
}

run_http_smoke_tests() {
    require_command curl
    curl --fail --silent --show-error --max-time 10 http://localhost:8000/health >/dev/null
    curl --fail --silent --show-error --max-time 10 http://localhost:3000/ >/dev/null
}

verify_compose() {
    require_command docker
    (cd "$repo_root" && docker compose config --quiet)

    if [[ "$full_docker" == false ]]; then
        echo "[通过] Compose 配置检查（使用 --full-docker 执行构建与健康检查）"
        return
    fi

    (cd "$repo_root" && docker compose up --build -d)

    local deadline=$((SECONDS + 180))
    local ready=false
    local -a container_ids=()
    local state
    while ((SECONDS < deadline)); do
        mapfile -t container_ids < <(cd "$repo_root" && docker compose ps -q)
        if ((${#container_ids[@]} == 4)); then
            ready=true
            for container_id in "${container_ids[@]}"; do
                state="$(compose_service_state "$container_id")"
                if [[ "$state" != healthy && "$state" != running ]]; then
                    ready=false
                    break
                fi
            done
        fi
        [[ "$ready" == true ]] && break
        sleep 3
    done

    if [[ "$ready" != true ]]; then
        (cd "$repo_root" && docker compose ps)
        fail "Compose 服务未能在 3 分钟内全部就绪"
    fi

    run_http_smoke_tests
    echo "[通过] Compose 构建与健康检查"
}

echo "GroundDesk Agent Harness 统一门禁（Linux）"
echo "========================================"

cd "$repo_root"
run_python_gate scripts/harness/check_secrets.py
run_python_gate scripts/harness/check_architecture.py
run_python_gate scripts/harness/check_embedding_contract.py
run_backend_tests
run_frontend_tests
verify_compose

echo "========================================"
echo "[通过] 全部 Harness 门禁"
