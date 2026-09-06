# 开发者 B 阶段一报告：Agent 全栈基线与公共契约

## 1. 执行结论

阶段一已经完成。本阶段只进行了代码、提交历史、计划、测试和运行环境审计，并冻结后续阶段使用的公共契约；没有修改运行时代码、数据库 Schema 或部署配置。

当前项目已经具备 Hybrid Retrieval、Citation、基础 Grounding 和 LangGraph Interrupt/Resume，但尚未完成安全的人工审核 UI、原客服业务持久化接入和 Agent Evaluation。因此现状属于“AI 工作流骨架可以单元演示”，还不能视为双人计划中的最终全栈闭环。

## 2. 执行环境与工作区

| 项目 | 状态 |
|---|---|
| Git 分支 | `main` |
| 基线提交 | `fd88543` |
| 远端同步 | `main...origin/main`，无领先或落后 |
| 审计开始前工作区 | 干净 |
| Python 测试命令 | 当前主机没有 `pytest`/`uv` |
| 前端测试命令 | 有 `npm`，但未安装 `node_modules` |
| Docker | CLI 可用，当前 Compose 服务未运行 |

阶段一新增两份文档：

- `docs/developer-b-agent-fullstack-execution-plan.md`；
- `docs/developer-b-phase-1-baseline-contract-report.md`。

## 3. 当前两条实际调用链

### 3.1 新 LangGraph 主链路

应用 lifespan 会初始化 Hybrid Retrieval Service 和 `support_graph`。正常 Web 异步请求进入：

```text
POST /api/chat
→ Redis job=processing
→ FastAPI BackgroundTask
→ _run_workflow()
→ run_support_graph()
→ rewrite_query
→ Hybrid Retrieval Service
   ├── pgvector
   ├── BM25
   ├── RRF
   └── LLM Reranker / safe fallback
→ generate（文档摘录拼接）
→ grounding_check
   ├── completed
   └── interrupt / waiting_review
```

已验证事实：

- `rewrite_query` 当前只清理首尾和重复空白；
- Reranker 位于 Retrieval Service 内，不是独立 Graph 节点；
- `generate` 当前取 Top 3 文档各自前 280 个字符并附加 Citation；
- Grounding 只确定性检查是否有文档、是否有 Citation、Citation ID 是否属于本次文档集合；
- 高风险识别使用退款、法律和删除账户的中英文关键词；
- Checkpointer 是 `InMemorySaver`。

### 3.2 旧 OpenAI Agents SDK 链路

当 `support_graph` 不存在时，`_run_workflow()` 会回退到 `run_agent()`：

```text
run_agent()
→ OpenAI Agents SDK / Qwen Chat Completions
→ 11 个 Function Tool
→ 客户、工单、会话、知识库、发送、升级和指标
```

Redis 不可用时，Gmail 和 WhatsApp 同步分支也会直接使用旧 `run_agent()`。

已验证事实：新 Graph 不会调用客户识别、创建工单、保存消息、发送响应和记录指标工具。正常生产入口因此存在两套语义不同的执行路径。

## 4. 当前公共契约差异

### 4.1 ID

当前 `_run_workflow()` 同时把 `job_id` 写入 `run_id` 和 `conversation_id`。这意味着 Graph State 中的 `conversation_id` 不是数据库真实会话 ID。

冻结方案：

- `run_id` 是 Graph 和审核主键；
- `job_id` 是兼容轮询字段，值与 `run_id` 相同；
- `correlation_id` 首次请求时与 `run_id` 相同；
- `conversation_id` 和 `ticket_id` 必须来自 PostgreSQL 业务记录。

### 4.2 状态

当前后端使用自由字符串，前端 TypeScript 使用联合类型。冻结状态为：

```text
processing | waiting_review | completed | rejected | failed
```

后续后端应使用 Enum/Literal 约束，并明确终态与合法转换。

### 4.3 Chat 和 Job 响应

当前后端 `ChatResponse` 已包含：

```text
response
correlation_id
status
citations
requires_human_review
review_reason
```

前端 `ChatResponse` 仍只有 `response` 和 `correlation_id`，字段没有同步。

当前 `JobStatus` 没有 `run_id`、真实 `conversation_id` 和 `ticket_id`。后续保留 `job_id/response` 兼容字段并增加这些业务 ID。

### 4.4 Waiting Review 可见性

当前 Job API 会返回待审核 `response` 草稿。前端收到后会：

1. 把客户消息状态更新为 `completed`；
2. 把内部草稿追加为 Agent 消息；
3. 在同一客户页面显示 Approve、Edit 和 Reject 控件。

这违反“未审批草稿不能发送给客户”的安全边界。

冻结方案：

- 客户 Job API 在 `waiting_review` 时 `response=null`；
- 客户页面只显示等待人工处理；
- 审核详情 API 才能返回 `draft_answer`；
- 审核控件移动到独立 `/reviews` 页面。

## 5. 人工审核基线

当前已有：

- Graph `interrupt()`；
- `approve`、`edit` 和 `reject` 三种节点分支；
- `POST /api/reviews/{run_id}`；
- Redis Job 状态更新；
- 1 个 Graph approve 测试；
- 1 个 Review API approve 测试；
- 1 个前端 waiting_review 轮询测试。

当前缺少：

- 待审核列表；
- 审核详情；
- Review Repository；
- `edit` 非空校验；
- 未知 Run ID 行为；
- 重复请求幂等；
- 终态冲突检测；
- edit 后重新 Citation/Grounding；
- reject 和失败测试；
- 审核结果回写客户消息；
- 审核页面测试。

## 6. Agent 和业务持久化基线

原项目已有以下 Function Tool：

- 查找或创建客户；
- 获取客户历史；
- 创建、读取和更新工单；
- 保存和读取会话消息；
- 搜索知识库；
- 发送响应；
- 升级人工；
- 记录指标。

新 Graph 当前只使用 Retrieval Service，不使用这些业务工具。后续不能在 `api/main.py` 中直接拼接 SQL 或逐个调用底层实现，应通过新的 Application Service 连接业务持久化与 Graph。

## 7. Eval 和测试基线

### 7.1 已有证据

- Retrieval Eval：30 条数据；
- Vector-only、Hybrid、Hybrid + Reranker 三策略运行器；
- Recall@3、MRR、无答案准确率和 P50/P95；
- 最近检索报告记录后端 `294 passed, 4 skipped`、前端 `81 passed`；
- 当前阶段重新执行的 Secret、架构和 1536 维 Embedding 门禁全部通过。

### 7.2 当前不能确认

由于本地主机缺少 Python 测试依赖和前端 `node_modules`，阶段一没有重新执行完整后端、前端测试。最近报告中的通过数量是仓库证据，但不是本轮环境重新验证结果。

### 7.3 测试覆盖缺口

- API 测试 fixture 默认 `support_graph=None`，Chat API 主要测试旧 Runner 回退；
- 没有真实 Graph 的 HTTP 集成测试；
- 没有 Agent Eval；
- 没有 Grounded Answer Rate 和 Correct Escalation Rate；
- 没有两条核心 Demo 的当前环境运行证据。

## 8. 已验证事实、推断和待确认事项

### 8.1 已验证事实

- 检索侧功能和接口已经提交；
- Graph、Citation 和 Interrupt/Resume 已经提交；
- 客户页面会显示待审核草稿和审核按钮；
- 新 Graph 没有 CRM 持久化；
- Agent Eval 不存在；
- 公共 API 字段没有完全同步。

### 8.2 基于证据的推断

- 现有代码可完成 Fake Graph 的正常回答和人工批准演示；
- 在真实服务可用时，Hybrid Retrieval 应能被 Graph 调用；
- 当前客户/审核 UI 边界不适合作为最终演示流程。

这些推断仍需端到端测试确认。

### 8.3 待后续验证

- 当前 Compose 是否能从干净环境完整构建；
- Qwen Reranker 当前供应商延迟和错误率；
- PostgreSQL、Redis 和 Graph 同时运行时的两条真实 Demo；
- 另一位开发者是否存在未推送的共享文件改动。

## 9. 阶段一验证结果

```text
[通过] 密钥扫描
[通过] 架构边界检查
[通过] Embedding 契约：1536 维
[通过] git diff --check（阶段一运行前）
[未执行] Backend pytest：主机没有 pytest/uv
[未执行] Frontend Vitest：node_modules 未安装
[未执行] Compose：阶段一只做基线审计，当前服务未运行
```

## 10. 回滚方法

阶段一只新增文档，没有运行时代码、数据库或配置变化。如需回滚，只需删除本阶段新增的两份文档。

## 11. 阶段二预计文件

预计新增：

```text
agent/review/__init__.py
agent/review/models.py
agent/review/repository.py
tests/test_agent/test_review_repository.py
web/src/app/reviews/page.tsx
web/src/app/reviews/[runId]/page.tsx
```

预计修改：

```text
agent/context.py
agent/state.py
agent/graph.py
api/main.py
tests/test_agent/test_graph.py
tests/test_api/test_main.py
web/src/lib/types.ts
web/src/lib/api.ts
web/src/hooks/useJobPolling.ts
web/src/components/SupportForm.tsx
web/src/__tests__/
```

不修改数据库迁移和 Embedding 契约。Review Repository 优先复用 Redis；`InMemorySaver` 限制继续保留并明确记录。
