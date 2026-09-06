# 开发者 B：Agent 与全栈闭环分步执行方案

## 1. 目标

本方案用于在现有 Hybrid Retrieval 基础上，分步骤完成 AI 客服 Agent、人工审核、业务持久化、Agent Evaluation 和前端闭环。

目标不是重写已有检索模块，而是把已经完成的 pgvector、BM25、RRF、Reranker 和置信度信号接入一条可验证的客服业务链路：

```text
客户请求
   ↓
创建客户、工单和会话
   ↓
Query Rewrite
   ↓
Hybrid Retrieval + Reranker
   ↓
生成带 Citation 的回答
   ↓
Grounding Check
   ├── 通过 → 保存并交付最终回答
   └── 不通过/高风险 → 保存内部草稿并等待人工审核
                              ↓
                        编辑、批准或拒绝
                              ↓
                        重新校验并交付
```

本方案必须完成：

- 收口 `SupportState`、API 状态和前端类型；
- 阻止 `waiting_review` 草稿提前展示给客户；
- 提供待审核列表、详情和幂等审批；
- 将 LangGraph 与原有客户、工单、会话、消息和指标链路集成；
- 完成真实 Query Rewrite、Grounded Generation 和确定性 Citation 校验；
- 建立 Agent Eval，统计 Grounded Answer Rate、Correct Escalation Rate 和端到端延迟；
- 使用两条核心 Demo 完成最终验收。

## 2. 范围和非目标

### 2.1 本轮范围

- 单实例演示环境；
- Web 客户端和基础审核后台；
- Redis 中的异步任务和审核索引；
- LangGraph `InMemorySaver`；
- PostgreSQL 中的现有客户、工单、会话、消息和指标表；
- Qwen OpenAI-compatible Chat/Embedding 接口；
- 现有 Hybrid Retrieval Service；
- Fake/Mock 自动化测试和受显式授权保护的真实模型评测。

### 2.2 本轮不做

- 登录、RBAC、多租户和审核任务分配；
- PostgreSQL Checkpointer；
- Celery、Kafka 或独立 Worker；
- Gmail、WhatsApp 真实出站；
- 知识库 CMS；
- 多 Agent、MCP、长期记忆和模型微调；
- 大规模压测和生产级可观测平台。

这些能力不阻塞基础版验收，但必须在 README 和阶段报告中记录为限制。

## 3. 当前已验证基线

### 3.1 已完成能力

- `AgentContext` 在服务启动时创建数据库、模型和 Redis 依赖；
- Hybrid Retrieval Service 已实现 Vector、BM25、RRF、LLM Reranker 和安全降级；
- 检索缓存已包含完整的结构化检索结果；
- Top-1 Vector 相似度低于 `0.40` 会产生低置信度信号；
- `SupportState`、基础 LangGraph、Citation 和 `interrupt/resume` 已存在；
- Web 已能轮询 `processing`、`completed`、`failed` 和 `waiting_review`；
- Retrieval Eval 已有 30 条数据和真实校准报告。

### 3.2 当前主要缺口

- `waiting_review` 草稿会进入客户聊天记录，客户页面同时暴露审核按钮；
- 没有待审核列表和审核详情 API/页面；
- Review API 没有幂等语义，人工编辑后不会重新执行 Grounding；
- 新 Graph 没有执行客户识别、工单创建、消息保存、工单状态和指标记录；
- `conversation_id` 当前使用 `job_id` 占位；
- Query Rewrite 只做空白标准化，Generation 只拼接文档摘录；
- API 测试主要把 `support_graph` 设为 `None`，没有覆盖真实 Graph HTTP 路径；
- 没有 Agent Eval、Grounded Answer Rate、Correct Escalation Rate 和端到端 P95；
- README 仍主要描述旧 OpenAI Agents SDK 工作流，与新 Graph 实际行为不完全一致。

## 4. 执行原则

1. 保持依赖方向：`web -> api -> agent/application -> retrieval/tools -> infrastructure`。
2. FastAPI 只做传输校验和响应映射，不写业务 SQL、Prompt 或 Graph 节点逻辑。
3. Graph 依赖抽象服务；数据库、Redis 和模型客户端只在组合边界创建。
4. `waiting_review` 中的回答是内部草稿，不是客户可见的最终回答。
5. Citation 只能来自本次最终检索文档，人工编辑后必须重新校验。
6. Review 操作必须幂等，重复操作不得重复保存消息或更新工单。
7. 自动化测试不调用真实模型；真实供应商评测必须要求显式费用授权。
8. 每个阶段独立验证、独立报告，失败时不把问题带入下一阶段。
9. 保留现有外部字段兼容性，破坏性 API 变化必须提供迁移说明。

## 5. 公共契约冻结方案

### 5.1 ID 语义

| 字段 | 语义 |
|---|---|
| `run_id` | LangGraph 运行和人工审核主键，同时贯穿日志 |
| `job_id` | 异步轮询兼容字段，基础版与 `run_id` 值相同 |
| `correlation_id` | HTTP/日志追踪兼容字段，首次请求时与 `run_id` 值相同 |
| `conversation_id` | PostgreSQL 中真实会话 ID，不再使用 `job_id` 占位 |
| `ticket_id` | PostgreSQL 中真实工单 ID |

### 5.2 状态枚举

```text
processing
waiting_review
completed
rejected
failed
```

允许的主要转换：

```text
processing -> completed
processing -> waiting_review
processing -> failed
waiting_review -> completed
waiting_review -> rejected
waiting_review -> failed
```

`completed`、`rejected` 和 `failed` 是终态。对相同终态重复提交相同审核动作时返回原结果；冲突动作返回 `409`。

### 5.3 客户轮询响应

继续保留现有 `job_id` 和 `response` 字段，新增或统一：

```json
{
  "job_id": "run-id",
  "run_id": "run-id",
  "conversation_id": "database-conversation-id",
  "ticket_id": "database-ticket-id",
  "status": "completed",
  "response": "最终客户回答",
  "citations": [],
  "requires_human_review": false,
  "review_reason": null,
  "error": null,
  "retry_after": null
}
```

当状态为 `waiting_review` 时，客户轮询响应的 `response` 必须为 `null`，不得包含内部草稿。

### 5.4 审核响应

审核详情可以返回内部字段：

```json
{
  "run_id": "run-id",
  "status": "waiting_review",
  "original_query": "用户问题",
  "draft_answer": "AI 草稿",
  "citations": [],
  "review_reason": "high_risk_request"
}
```

基础版接口：

```text
GET  /api/reviews
GET  /api/reviews/{run_id}
POST /api/reviews/{run_id}
```

`POST` 动作支持 `approve`、`edit`、`reject`。`edit` 必须包含非空 `answer`。

## 6. 目标模块结构

```text
agent/
├── application/
│   ├── models.py
│   └── support_service.py
├── nodes/
│   ├── rewrite.py
│   ├── generate.py
│   └── grounding.py
├── review/
│   ├── models.py
│   └── repository.py
├── graph.py
└── state.py

evals/
├── agent_dataset.py
├── agent_eval.py
└── datasets/agent_v1.jsonl

web/src/app/reviews/
├── page.tsx
└── [runId]/page.tsx
```

实际实现优先复用现有模块。如果拆分会显著增加本轮风险，可以先保持小模块并在报告中说明。

## 7. 阶段一：基线审计与契约冻结

### 7.1 目标

把当前实现与双人计划逐项对账，冻结 ID、状态、客户可见字段、审核字段和回滚边界。

### 7.2 操作清单

- 检查当前分支、未提交改动和最近提交；
- 记录旧 Agent 与新 Graph 两条调用路径；
- 核对 Pydantic、TypeScript、API 客户端和测试中的字段；
- 核对 `waiting_review` 草稿的实际可见性；
- 核对 Review API 的幂等、恢复和错误行为；
- 核对 Graph 是否执行真实客服业务持久化；
- 记录当前可执行测试环境和门禁结果；
- 明确每个后续阶段的文件边界和回滚方法。

### 7.3 产物

- `docs/developer-b-phase-1-baseline-contract-report.md`；
- 本执行方案中的公共契约；
- 下一阶段修改文件清单。

### 7.4 完成标准

- 已验证事实、推断和待确认事项明确分开；
- 客户响应与审核响应的字段边界清晰；
- 后续实现不需要临时猜测 ID 和状态语义；
- Secret、架构和 Embedding 契约门禁通过。

## 8. 阶段二：审核安全边界与审核后台闭环

### 8.1 目标

保证未审批草稿不会交付客户，并完成可查询、可恢复、幂等的基础审核闭环。

### 8.2 操作清单

- 定义 Review Record、Decision 和公开响应模型；
- 建立 Review Repository，保存待审核索引、草稿、原因和终态结果；
- 新增待审核列表和详情 API；
- 收紧 Review Decision 参数校验；
- 实现终态幂等和冲突动作 `409`；
- 人工编辑后重新执行 Citation/Grounding 校验；
- 客户 Job API 在 `waiting_review` 时隐藏草稿；
- 新建独立审核列表和详情页面；
- 客户页面只显示等待审核提示；
- 审核完成后客户轮询能够获得最终答案或拒绝状态。

### 8.3 测试

- 客户接口不泄露草稿；
- 列表、详情、批准、编辑、拒绝；
- 非法动作、空编辑、未知 Run ID；
- 重复相同动作幂等；
- 终态冲突动作返回 `409`；
- 编辑后 Citation 无效不能直接完成；
- 前端审核加载、成功、失败和重试。

### 8.4 完成标准

- 两类 UI 的数据边界明确；
- 未审批答案不会进入客户消息；
- 审核动作重复执行不会产生重复副作用；
- Review API 和前端类型一致。

### 8.5 回滚

回滚 Review Repository、三个 Review API 和 `/reviews` 页面；保留现有 Graph interrupt，不修改数据库 Schema。

## 9. 阶段三：客服业务 Application Service 集成

### 9.1 目标

将新 Graph 与原项目的客户、工单、会话、消息、状态和指标能力合并成一条主链路。

### 9.2 操作清单

- 建立 `SupportApplicationService`；
- 在执行 Graph 前识别或创建客户；
- 创建真实工单和会话，写入真实 `ticket_id/conversation_id`；
- 保存客户入站消息；
- Graph 完成后保存 Agent 最终消息并更新工单；
- Graph 等待审核时保存内部审核记录，不保存客户可见出站消息；
- 审批完成后只保存一次最终消息和最终状态；
- 记录响应时间、检索策略、是否升级和审核结果；
- Web、Gmail 和 WhatsApp 入站统一进入 Application Service；
- 保留旧 `run_agent()` 作为显式开关或短期故障回退，不再作为隐式业务分叉。

### 9.3 测试

- 正常回答的客户、工单、会话和消息写入顺序；
- 等待审核时没有出站消息；
- 批准或编辑后只保存一条最终消息；
- 拒绝后工单状态正确；
- 任一持久化步骤失败时不返回虚假成功；
- Webhook 与 Web 使用同一 Application Service；
- Correlation ID、Run ID、Ticket ID 和 Conversation ID 可追踪。

### 9.4 完成标准

- 正常生产入口不再绕过 CRM；
- `conversation_id` 和 `ticket_id` 是真实数据库 ID；
- Graph 与原 11 个工具能力不存在两套互相矛盾的主流程；
- FastAPI 仍保持薄层。

### 9.5 回滚

通过组合根恢复旧 Runner Adapter；不删除原工具，不修改现有数据库表。

## 10. 阶段四：Query Rewrite、Generation 与 Grounding 完善

### 10.1 目标

用模型生成自然、可引用的客服回答，同时用确定性校验阻止越界 Citation 和无依据内容。

### 10.2 操作清单

- Query Rewrite 输出单一检索 Query；
- Rewrite 失败时记录原因并回退原 Query；
- Generation 只接收最终 Top 3 文档和最少客户上下文；
- 模型返回结构化回答和 Citation 文档 ID；
- 限制文档数量、正文长度和模型输出长度；
- 校验未知、重复、缺失和未使用 Citation；
- Grounding 失败进入人工审核；
- 高风险规则继续保留确定性关键词/分类检查；
- 人工编辑后再次运行同一 Grounding 校验；
- 模型供应商失败明确标记为 `failed` 或可解释的安全回退。

### 10.3 测试

- Rewrite 正常和失败回退；
- Generation 正常结构化输出；
- 未知、重复、缺失 Citation；
- 无检索结果不调用 Generation；
- 高风险请求始终进入审核；
- 供应商超时和错误载荷；
- 人工编辑后的重新校验。

### 10.4 完成标准

- 客户看到的是自然回答而不是文档摘录拼接；
- 回答的每个公开 Citation 都能映射到本次 Top 3；
- 模型异常不会绕过人工审核或返回虚假成功。

### 10.5 回滚

保留当前确定性摘录生成器作为可注入的测试/安全实现；不改变 Embedding 模型和向量契约。

## 11. 阶段五：Agent Eval

### 11.1 目标

用可重复的数据集评估 Agent 的 Grounding、升级路由和端到端延迟，不用少量手工 Demo 代替指标。

### 11.2 数据集

第一版约 30 条，包含：

- 正常可回答问题；
- 中英文和中英混合问题；
- 知识库无答案问题；
- 退款、法律和删除账户等高风险问题；
- Citation 缺失或越界的模拟生成结果；
- Reranker 降级和模型错误场景。

每条至少标注：

```json
{
  "id": "agent-001",
  "query": "如何重置密码？",
  "expected_status": "completed",
  "should_escalate": false,
  "expected_document_titles": ["Password Reset"],
  "tags": ["answerable", "zh"]
}
```

### 11.3 指标

- Grounded Answer Rate；
- Correct Escalation Rate；
- Citation Validity Rate；
- 高风险漏升级率；
- 正常问题误升级率；
- P50/P95 端到端延迟；
- 失败案例和路由原因。

### 11.4 运行模式

- 默认 Fake 模式：CI 可重复、无模型费用；
- 可选 Live 模式：必须显式传入 `--execute-live`；
- 生成报告默认写入已忽略的 `evals/reports/`。

### 11.5 完成标准

- 一个命令生成 Agent Eval 报告；
- 指标由脚本计算，不手工填写；
- 失败可以定位到 Query、Citation 和路由原因；
- 自动化测试不需要 API Key。

## 12. 阶段六：最终联调、文档和 Demo 验收

### 12.1 正常回答 Demo

```text
用户询问如何重置密码
→ 创建客户、工单和会话
→ Rewrite + Hybrid Retrieval + Reranker
→ 生成带 Citation 的回答
→ Grounding 通过
→ 保存出站消息并完成工单
→ 客户看到最终回答和引用
```

### 12.2 人工审核 Demo

```text
用户提出退款或知识库外问题
→ 创建客户、工单和会话
→ 状态变为 waiting_review
→ 客户只看到等待审核提示
→ 审核后台看到草稿、原因和引用
→ 人工编辑并批准
→ 再次 Grounding
→ 保存唯一最终消息并更新工单
→ 客户轮询得到最终回答
```

### 12.3 验收清单

- 后端、前端、Graph、Application、Review 和 Eval 测试通过；
- Secret、架构、Embedding 契约检查通过；
- Compose 构建、健康检查和两条 Demo 通过；
- README 与真实主链路一致；
- 文档记录测试数量、Eval 指标、限制和回滚；
- `git diff --check` 和工作区产物检查通过。

## 13. 推荐执行节奏

| 阶段 | 工作内容 | 可验收产物 |
|---|---|---|
| 1 | 基线和契约 | 基线报告、冻结契约、风险清单 |
| 2 | Review 闭环 | 安全客户响应、审核 API、审核页面 |
| 3 | Application 集成 | 真实客户/工单/会话/消息闭环 |
| 4 | Rewrite/Generation/Grounding | 自然回答、结构化 Citation、安全校验 |
| 5 | Agent Eval | 约 30 条数据、指标脚本、失败报告 |
| 6 | 联调和文档 | 两条 Demo、完整 Harness、最终报告 |

时间取决于本地依赖和真实服务是否可用。没有供应商费用授权时，只执行 Fake/Mock 验证。

## 14. 每阶段固定执行模板

每个阶段按以下顺序执行：

1. 检查当前分支和未提交改动；
2. 读取阶段涉及的规则、工作流和现有代码；
3. 列出预计修改文件和公开契约影响；
4. 先补领域模型和测试，再连接上层；
5. 执行专项测试和静态门禁；
6. 生成阶段报告；
7. 检查工作区，避免提交缓存、报告产物和密钥；
8. 阶段验收通过后再进入下一阶段。

阶段报告固定包含：

```text
完成内容：
未完成内容：
接口变化：
验证方式：
评测结果：
已知限制：
回滚方法：
下一阶段：
```

## 15. 第一阶段立即执行项

第一阶段只冻结事实和契约，不修改运行时代码。完成后输出：

- 旧 Agent 与新 Graph 的实际调用链；
- 当前客户响应、审核响应和状态差异；
- 客户草稿泄露和业务持久化缺口；
- 当前测试证据与无法执行项；
- 阶段二预计新增和修改的文件。
