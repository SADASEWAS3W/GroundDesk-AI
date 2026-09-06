# 开发者 B 阶段三报告：客服业务 Application Service 集成

## 1. 执行结论

阶段三已经完成。Web、Gmail 和 WhatsApp 的正常主入口现在可以统一进入 `SupportApplicationService`，在执行 LangGraph 前创建真实客户、工单和会话，并保存入站消息；Graph 完成后再交付出站消息、更新工单和记录指标。

新 Graph 不再天然绕过 CRM。旧 `run_agent()` 仅在 Application Service/Graph 未配置时作为兼容回退。

## 2. 新增模块

```text
agent/application/models.py
agent/application/support_service.py
```

### 2.1 SupportRequest

统一承载：

- `run_id`；
- 客户原始消息；
- email/phone 标识；
- channel；
- 可选客户名称。

WhatsApp 自动使用 `phone` 标识，Web/Gmail 使用 `email` 标识。

### 2.2 SupportBusinessContext

统一保存：

- `customer_id`；
- `ticket_id`；
- `conversation_id`；
- `channel`。

这些 ID 来自现有数据库工具返回值，不再由 `job_id` 占位。

### 2.3 ToolBackedSupportPersistence

Application Service 没有复制业务 SQL，而是通过 Adapter 复用原项目已有工具：

```text
find_or_create_customer
create_ticket
save_message
update_ticket
send_response
escalate_to_human
log_metric
```

必要操作返回结构化 `error` 时抛出 `SupportPersistenceError`，上层不会把失败转换成虚假成功；Metrics 继续保持 best-effort。

## 3. 当前统一业务流程

### 3.1 正常回答

```text
接收 Web/Webhook 请求
→ find_or_create_customer
→ create_ticket + conversation（原工具事务）
→ save_message(inbound)
→ ticket: open -> in_progress
→ LangGraph / Hybrid RAG
→ send_response（同时保存 outbound）
→ ticket: in_progress -> resolved
→ log_metric(auto_resolved)
→ 返回真实 ticket_id / conversation_id
```

### 3.2 等待人工审核

```text
创建客户、工单、会话并保存 inbound
→ LangGraph 返回 waiting_review
→ escalate_to_human
→ Review Repository 保存内部草稿和业务 ID
→ log_metric(escalated)
→ 客户响应 response=null
```

### 3.3 人工批准或编辑

```text
Review API 恢复 Graph
→ SupportApplicationService.deliver_reviewed()
→ send_response 保存唯一出站消息
→ Review/Job 状态改为 completed
→ 客户轮询得到最终回答
```

人工拒绝不会保存出站消息。

## 4. API 接入变化

- API lifespan 在数据库、Redis、Retrieval Service 和 Graph 初始化后创建 `SupportApplicationService`；
- Web Chat 将 message、email、channel 和 name 作为结构化 `SupportRequest` 传递；
- Gmail/WhatsApp 异步和 Redis-down 同步路径使用同一入口；
- 旧 Runner 回退仍保留原 `[Customer: ..., Channel: ...]` 上下文格式；
- `JobStatus` 和 `ChatResponse` 可以返回真实 `conversation_id/ticket_id`。

## 5. 测试

新增 Application Service 测试：

- 正常回答返回真实业务 ID 并调用 complete；
- 高风险问题只调用 escalate，不交付草稿；
- Review Record 保存真实业务 ID；
- 人工审核完成后调用 reviewed delivery；
- Chat API 在配置 Application Service 时传递结构化客户信息；
- 旧 Runner 回退仍兼容原上下文消息。

验证结果：

```text
Backend full suite: 312 passed, 4 skipped
Frontend full suite: 86 passed
Python compileall: passed
Secret gate: passed
Architecture gate: passed
Embedding contract gate: passed
git diff --check: passed
```

## 6. 数据和迁移分析

本阶段没有新增数据库表或字段，因此不需要数据库迁移。

复用现有数据约束：

- 客户标识具有唯一约束；
- 工单和会话由原工具在同一事务创建；
- 工单保持 forward-only 状态转换；
- 消息继续关联真实 conversation；
- Agent Metrics 继续使用原表。

## 7. 已知限制

- Application Service 当前使用 `general/billing` 的简化确定性分类，以及 `medium/high` 优先级；更丰富分类仍可后续增加；
- 当前没有单独的情感模型，入站消息 `sentiment` 暂存为 `null`；
- 高风险/低置信度工单进入 `escalated` 后保持该状态，即使人工最终回答也不反向改为 `resolved`，符合现有 forward-only 约束；
- 出站消息与工单状态更新跨越多个已有工具调用，不是同一数据库事务；在极端的中途失败场景可能需要人工核对；
- 尚未使用真实 PostgreSQL/Redis 执行本阶段端到端集成测试，当前验证由 Application Fake 和既有工具单元测试构成；
- Gmail/WhatsApp 仍只保存出站消息，没有真实外部发送。

## 8. 回滚方法

- 从 API lifespan 移除 `SupportApplicationService`；
- 恢复 `_run_workflow()` 直接调用 Graph/旧 Runner；
- 删除 `agent/application/`；
- 不需要数据库迁移或数据回滚；已经由测试/演示创建的数据按普通工单数据处理。

## 9. 下一阶段

阶段四将完善 Query Rewrite、模型回答生成和 Grounding：

- 单 Query Rewrite，失败回退原问题；
- Qwen 结构化生成自然回答和 Citation ID；
- 确定性校验 Citation marker、文档 ID 和来源集合；
- 无证据不调用生成；
- 人工编辑复用同一 Citation 校验；
- 自动化测试使用 Fake Generator/Rewriter，不产生模型费用。
