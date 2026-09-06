# 开发者 B 阶段六报告：最终联调与验收

## 1. 执行结论

阶段六已经完成，开发者 B 的六阶段计划全部落地。

当前主流程已形成以下闭环：

```text
Web / Gmail / WhatsApp 入站
→ FastAPI
→ SupportApplicationService 创建真实 CRM 上下文
→ LangGraph Query Rewrite
→ Hybrid Retrieval + Reranker
→ Qwen Grounded Generation
→ Citation / Grounding Check
→ 自动交付或 Human Review
→ 保存最终消息并向客户返回终态
```

README 已从上游旧 Agents SDK 叙事更新为当前实现，两个核心 Demo 已通过离线 HTTP 验收，前后端测试、生产构建、静态门禁和四服务 Compose 健康检查均通过。

## 2. 阶段六新增和收尾内容

### 2.1 两条核心 Demo 验收

新增 `tests/test_api/test_fullstack_demo.py`，通过真实 FastAPI Route、Application Service、LangGraph、Review Repository 和 Fake Persistence 验证：

1. 正常知识问题生成带 Citation 的回答，返回真实 `ticket_id/conversation_id`，并按 `prepare -> complete` 顺序交付；
2. 退款问题进入 `waiting_review`，客户响应隐藏草稿；审核详情可见草稿；批准后只交付一次；重复批准保持幂等；客户 Job 查询取得最终回答。

前端 `test-review-customer-flow.test.tsx` 同时验证：

- 客户页面不展示内部草稿和审批按钮；
- 审核完成后继续轮询并展示最终回答；
- Redis 不可用导致同步 `waiting_review` 时，前端仍使用 `run_id` 继续轮询。

### 2.2 收尾代码审计修复

- 扩充高风险表达，覆盖 `delete my account`、账单争议、chargeback、律师/诉讼和中英文销户表达；
- Citation 校验增加“声明但未使用”的引用检查；
- Qwen Generation 增加 800 tokens 输出上限；
- `SupportRequest` 校验空字段和渠道枚举；
- FastAPI Chat Contract 将 channel 限定为 `web/gmail/whatsapp`；
- Metrics 调用保持真正的 best-effort，不影响客户主流程；
- Job Store 未命中时回退查询 Review Repository，补齐 Redis-down 审核续接；
- Compose 的 `.env` 改为可选，使无密钥环境仍可执行配置检查；
- Python/npm Dockerfile 增加可覆盖的包源 Build ARG，默认仍使用官方源。

### 2.3 README

根 README 现在准确描述：

- 上游项目背景和本分支改造目标；
- 当前 LangGraph/Hybrid RAG/Application/Review 架构；
- 自动回答与人工审核两条流程；
- ID、状态和客户可见性契约；
- API、项目结构、启动、测试和 Eval 命令；
- 面试讲解重点；
- 当前生产化限制与升级方向。

旧 OpenAI Agents SDK Runner 被明确标注为兼容回退，不再作为当前主链路描述。

## 3. 最终自动化验证

### 3.1 后端

```text
pytest: 331 passed, 4 skipped
Python compileall: passed
```

4 个 skip 是需要真实服务/显式环境条件的既有集成测试。唯一 warning 是 LangGraph Checkpoint Serializer 的未来默认值变更。

### 3.2 前端

```text
Vitest: 87 passed
ESLint: passed, 0 errors
Next.js production build: passed
```

生产构建包含：

```text
/
/embed
/reviews
/reviews/[runId]
```

测试日志仍有既有 React `act(...)` 提示和 jsdom Canvas 未实现提示，不影响断言与构建结果。

### 3.3 Agent Eval

30 条 Offline Eval 的最终功能基线：

| 指标 | 结果 |
|---|---:|
| Expected Status Accuracy | 100% |
| Correct Escalation Rate | 100% |
| High-risk Miss Rate | 0% |
| False Escalation Rate | 0% |
| Grounded Answer Rate | 83.33% |
| Citation Validity Rate | 83.33% |
| Citation 故障拦截率 | 100% |
| Unexpected Failed Cases | 0 |

83.33% 来自 24 条进入生成的案例中刻意注入 4 条 Citation 故障；这些故障均被安全转入审核。Offline P50/P95 是毫秒级 Fake 执行开销，不代表真实供应商延迟。

### 3.4 仓库门禁

```text
Secret gate: passed
Architecture gate: passed
Embedding contract gate: passed (1536 dimensions)
docker compose config --quiet: passed
git diff --check: passed
```

当前 Linux 环境没有 `powershell/pwsh`，因此没有直接执行 `scripts/harness/run-all.ps1`。已逐项执行该脚本包含的所有门禁，并额外完成前端 Lint/Build 和 Full Compose 验收。

## 4. Docker Compose 验收

### 4.1 构建

以下镜像均成功完成多阶段构建：

```text
grounddesk-ai-api
grounddesk-ai-web
```

本地网络访问 Docker Hub/GHCR 较慢，验收时先通过镜像源取得相同 digest 的基础镜像，并通过 Build ARG 使用国内 Python/npm 镜像。Dockerfile 默认值仍为官方 PyPI/npm Registry。

### 4.2 启动与健康检查

使用非真实、不会触发模型调用的占位 Qwen 配置启动四服务，结果：

```text
postgres: healthy
redis: healthy
api: healthy
web: healthy

GET /health        -> 200 {"status":"ok"}
GET /health/ready  -> 200, database=connected, redis=connected
GET /              -> 200
GET /reviews       -> 200
```

验收后已停止并移除容器和 Compose Network；为避免未经请求的数据删除，没有删除 Docker 命名卷。

该检查证明容器构建、数据库 schema、Redis、API lifespan、Next.js standalone runner 和健康探针可运行，但不等同于真实 Qwen 端到端回答测试。

## 5. 数据与迁移

本轮没有新增或修改数据库表、字段和索引，因此没有数据库迁移，也不需要数据回滚。

Embedding 契约继续固定为 1536 维，知识库不需要重建。

新增 Review 元数据保存在 Redis/InMemory Repository：

- Redis Review Record TTL 为 24 小时；
- 待审核集合使用 `crm:reviews:pending`；
- Job Store 未命中时可从 Review Record 返回客户安全终态；
- LangGraph Checkpoint 仍为进程内存。

## 6. 未执行项

- 没有执行带 `--execute-live` 的 Retrieval Eval 或 Agent Eval，避免未授权的供应商费用；
- 没有使用真实 Qwen 完成聊天 Demo；
- 没有连接真实 Gmail/Twilio 出站；
- 没有多实例并发审批测试或压力测试；
- 没有直接运行 PowerShell Harness，原因是当前系统没有 PowerShell，已执行等价命令。

## 7. 剩余风险

1. `InMemorySaver` 导致进程重启后无法恢复 Graph interrupt；Redis Review 元数据可能仍在，但恢复会返回 checkpoint unavailable。
2. 审批是顺序幂等，不是 Redis CAS/数据库事务，多实例并发提交仍可能重复交付。
3. 出站消息、工单更新和指标跨多个 Tool 调用，不是一个数据库事务。
4. Grounding 保证 Citation 契约闭合，但不执行逐事实语义蕴含判断。
5. 审核页面没有 Auth/RBAC/审计，多租户或公网部署前不能直接上线。
6. Redis Compose 是单节点 AOF，不是高可用方案。
7. Gmail/WhatsApp 只完成入站和数据库出站记录，没有调用真实渠道 API。
8. 高风险判断仍是确定性短语表，需要持续扩充数据集并校准误判。

## 8. 建议的下一轮顺序

如果继续生产化，建议按以下顺序：

1. PostgreSQL/Redis 持久 Checkpointer，并定义 Review Record 与 Checkpoint 的一致性修复任务；
2. 审批 CAS/Outbox，保证多实例下最终回答只发送一次；
3. Auth、RBAC、Reviewer 审计和租户隔离；
4. 在费用授权后运行真实 Retrieval/Agent Eval，记录 Qwen P50/P95 和失败样本；
5. Gmail/Twilio 真实出站与重试/死信；
6. 语义 Grounding Judge 或 claim-level entailment Eval；
7. 并发压测、监控和告警。

## 9. 回滚方法

- API 可以恢复旧 Runner Adapter，原 11 个 Tool 未删除；
- Graph 可恢复确定性 Rewriter/Generator；
- Review 路由和页面可以独立移除；
- Application Service 可以从 API 组合根解除；
- Agent Eval 和报告不影响运行时；
- Compose 的 Build ARG 和 optional `.env` 可独立回滚；
- 因无数据库迁移，不需要 schema/data rollback。

## 10. 文档索引

- `developer-b-agent-fullstack-execution-plan.md`
- `developer-b-phase-1-baseline-contract-report.md`
- `developer-b-phase-2-review-workflow-report.md`
- `developer-b-phase-3-application-integration-report.md`
- `developer-b-phase-4-grounded-generation-report.md`
- `developer-b-phase-5-agent-eval-report.md`
- `developer-b-phase-6-final-integration-report.md`
