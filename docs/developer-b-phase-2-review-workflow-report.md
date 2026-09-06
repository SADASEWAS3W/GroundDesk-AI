# 开发者 B 阶段二报告：审核安全边界与审核后台闭环

## 1. 执行结论

阶段二已经完成。客户轮询接口不再暴露待审核草稿，审核数据进入独立 Review Repository，并新增待审核列表、详情和审批接口及页面。客户在审核期间继续轮询，只有审核完成后才会收到最终回答。

本阶段没有修改数据库 Schema、Embedding 模型或 Retrieval Service 公共契约。

## 2. 完成内容

### 2.1 Review 领域模型和 Repository

新增：

```text
agent/review/models.py
agent/review/repository.py
```

领域模型统一定义：

- `RunStatus`：`processing`、`waiting_review`、`completed`、`rejected`、`failed`；
- `ReviewAction`：`approve`、`edit`、`reject`；
- `ReviewRecord`：Run ID、原问题、内部草稿、Citation、审核原因、业务 ID 和最终决定。

Repository 提供：

- `InMemoryReviewRepository`：Redis 不可用及测试时的单进程回退；
- `RedisReviewRepository`：使用 `crm:review:{run_id}` 保存记录，并使用 `crm:reviews:pending` 维护待审核索引；
- 24 小时 TTL；
- 终态记录自动从待审核索引移除。

### 2.2 客户草稿隔离

当 Graph 返回 `waiting_review` 时：

- 内部 `answer` 保存到 `ReviewRecord.draft_answer`；
- Job 的客户公开 `response` 保存为 `null`；
- Job API 即使读取到旧数据，也会在 `waiting_review` 时强制隐藏 `response`；
- 客户页面不再显示 Approve、Edit 或 Reject；
- 客户页面只显示等待人工审核提示。

### 2.3 审核 API

新增：

```text
GET  /api/reviews
GET  /api/reviews/{run_id}
POST /api/reviews/{run_id}
```

行为：

- 列表只返回 `waiting_review` 记录；
- 详情返回内部草稿、原因和 Citation；
- `edit` 必须包含非空答案；
- 编辑答案中的 Citation 编号必须属于当前证据集合；
- 未知 Review 返回 `404`；
- 对相同终态重复相同决定返回已保存结果，不重复恢复 Graph；
- 对终态提交冲突决定返回 `409`；
- Checkpoint 不可用返回受控 `409`，不向外暴露内部异常。

全局异常响应也移除了原来的 `detail=str(exc)`，避免向外泄露供应商、SQL 或内部异常信息。

### 2.4 审核页面

新增：

```text
/reviews
/reviews/{runId}
```

待审核列表展示用户问题和审核原因；详情页展示：

- 原始问题；
- 内部草稿；
- 审核原因；
- Citation 证据；
- Approve、Approve Edited Answer 和 Reject。

基础版仍未增加登录和 RBAC，这与本轮非目标一致。

### 2.5 客户最终结果回收

`useJobPolling` 在 `waiting_review` 时不再停止：

- 首次进入审核时通知客户组件；
- 后续继续轮询，但不重复触发审核通知；
- 人工批准或编辑完成后，把最终回答和 Citation 加入客户会话；
- 人工拒绝后停止轮询并显示明确状态；
- 等待人工审核期间不应用普通 5 分钟处理超时。

同时修复了原流程中 completed 回调只传字符串、导致正常 Citation 丢失的问题。现在 completed 回调传递完整 `JobStatus`。

## 3. 公共接口变化

### 3.1 JobAccepted

新增：

```text
run_id
```

基础版中 `run_id == job_id`。

### 3.2 ChatResponse

新增或同步：

```text
run_id
conversation_id
ticket_id
status
citations
requires_human_review
review_reason
```

`response` 改为可空，以表示 `waiting_review` 尚无客户可见最终回答。

### 3.3 JobStatus

新增：

```text
run_id
conversation_id
ticket_id
```

后端 Pydantic、前端 TypeScript 和集中式 API 客户端已同步。

## 4. 测试

新增或扩展场景：

- Review Repository 只列出待审核记录；
- Repository 返回防御性副本；
- Job API 隐藏内部草稿；
- Review 列表和详情；
- 未知 Review；
- edit 空答案；
- 重复相同决定幂等；
- 冲突终态返回 `409`；
- Citation 编号校验；
- 客户等待审核后继续轮询；
- 客户不能看到草稿或审核按钮；
- 审核页面加载和编辑批准。

验证结果：

```text
Backend full suite: 308 passed, 4 skipped
Frontend full suite: 86 passed
ESLint: passed, 0 warnings
Next.js production build: passed
Python compileall: passed
Secret gate: passed
Architecture gate: passed
Embedding contract gate: passed
git diff --check: passed
```

测试中仍有既有的 React `act(...)` 和 jsdom Canvas 提示，不影响测试结果，本阶段没有新增对应依赖。

## 5. 安全结果

- 未审批草稿不再作为客户回答返回；
- 审核页面读取独立内部接口；
- 编辑答案执行确定性 Citation 编号校验；
- 对外 500 响应不再包含内部异常文本；
- 模型密钥和数据库连接仍只存在服务端。

## 6. 已知限制

- Redis Review Repository 与 LangGraph `InMemorySaver` 生命周期不同；进程重启后可能存在 Review 元数据但没有可恢复 Checkpoint，接口会返回 `409`；
- 幂等保证覆盖顺序重复请求，尚未实现跨进程并发 CAS；
- 人工编辑只重新执行 Citation 编号校验，完整 Grounding 将在阶段四统一实现；
- 审核后台没有登录、权限、分配、分页和 SLA；
- Redis 不可用的同步审核可以保存在内存，但客户页面无法跨请求轮询内存 Job 状态；正式 Demo 应启用 Redis。

## 7. 回滚方法

- 删除 `agent/review/` 和 `/reviews` 页面；
- 从 `AgentContext` 移除 `review_repository`；
- 恢复原单一 `POST /api/reviews/{run_id}`；
- 恢复 `useJobPolling` 在 `waiting_review` 时停止；
- 不需要数据库回滚。

## 8. 下一阶段

阶段三将建立 Application Service，把 Graph 与客户、工单、会话、消息、状态和指标持久化合并。主要目标是让正常 Web/Webhook 主链路不再绕过 CRM，并让 `conversation_id/ticket_id` 变为真实业务 ID。
