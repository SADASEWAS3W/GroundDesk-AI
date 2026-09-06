# Developer B：发布前验收报告

日期：2026-09-06

目标分支：`main`

## 1. 验收结论

当前代码已完成离线自动化测试、生产构建、依赖安全审计和四服务 Docker Compose 冒烟验证，可以推送。

本轮没有重新执行 Retrieval/Agent 大规模 Live Eval，也没有从测试或健康检查调用 Qwen，因此没有产生新一轮批量模型费用。

## 2. 自动化验证

```text
Backend pytest: 334 passed, 4 skipped
Frontend Vitest: 13 files passed, 87 tests passed
ESLint: passed, 0 errors, 0 warnings
Next.js production build: passed
Secret scan: passed
Architecture boundary: passed
Embedding contract: passed (1536 dimensions)
git diff --check: passed
```

后端测试保留一条 LangGraph Checkpoint serializer 上游未来默认值提示；前端测试保留 jsdom 未实现 Canvas 的提示。两者均不影响当前行为或测试结果。

## 3. 依赖安全处理

首次 Docker 构建发现 Next.js 16.1.6 及其生产依赖存在 4 个 High 漏洞，因此没有直接推送。

已完成：

- Next.js：`16.1.6 -> 16.3.4`；
- `eslint-config-next`：`16.1.6 -> 16.3.4`；
- Vitest：`4.0.18 -> 4.1.0`；
- Vite：更新到 `7.3.6`；
- 刷新允许版本范围内的开发工具依赖；
- 修复新版类型检查暴露的 `run_id` Mock 契约缺失；
- 修复新版 React Hooks Lint 暴露的 effect/ref 使用问题；
- 将 Vitest 配置改为原生 ESM 的 `vitest.config.mts`。

最终结果：

```text
npm audit: 0 vulnerabilities
npm audit --omit=dev: 0 vulnerabilities
Docker npm ci: found 0 vulnerabilities
```

安装日志提示 ESLint 9 已进入上游不再支持状态，但当前锁定版本没有安全 advisory，Lint 正常通过。后续可单独评估 ESLint 10 大版本迁移，不在本次发布中扩大范围。

## 4. Docker Compose 与 HTTP 冒烟

最终镜像使用当前工作区和更新后的锁文件重新构建。四个服务均为 healthy：

- PostgreSQL；
- Redis；
- FastAPI；
- Next.js。

HTTP 验证：

```text
GET http://localhost:8000/health       -> 200
GET http://localhost:8000/health/ready -> 200
GET http://localhost:3000/             -> 200
GET http://localhost:3000/reviews      -> 200
```

## 5. 敏感数据与生成产物

- `.env` 已被 `.gitignore` 忽略；
- `evals/reports/` 下的 Live Eval JSON 和日志已被忽略；
- 提交前密钥扫描通过；
- 不提交数据库 volume、缓存或查询级评测报告。

## 6. 保留决策

Retrieval v2 报告建议将阈值从 `0.40` 调整为 `0.425`，并在 Reranker 稳定性改善前评估以 `vector_only` 作为 Demo 默认策略。由于这会改变 `low_confidence -> HITL` 和 Graph 默认检索路径，本次发布不擅自修改，仍保持现有默认行为；详见 Retrieval v2 Live Eval 报告。
