# LangGraph、Hybrid RAG 与人工审核最终集成报告

## 完成内容

- 新增 `SupportState` 和显式 LangGraph 工作流：Rewrite → Retrieve → Generate → Grounding → Human Review/Finish；
- 应用启动时构建统一 Hybrid Retrieval Service，并加载 BM25 索引；
- 检索链路使用 pgvector、BM25、RRF、LLM Reranker 与评测校准的置信度策略；
- 新 Hybrid Service 使用 Redis 缓存完整检索结果，重复查询不再调用 Embedding 或 Reranker；
- 回答只从最终 Top 3 文档生成，Citation ID 只能来自本次检索结果；
- 无文档、Citation 缺失/越界、低置信度、退款/法律/删除账户请求进入人工审核；
- 使用 LangGraph `interrupt` 暂停，并通过审核 API 执行编辑、批准或拒绝后恢复；
- 异步 `job_id`、轮询、Redis 不可用同步降级保持兼容；
- 前端展示可展开 Citation 卡片和人工审核编辑/批准/拒绝控件。

## API 变化

`ChatResponse` 和 `JobStatus` 新增向后兼容字段：`citations`、`requires_human_review`、`review_reason`，并新增 `waiting_review`、`rejected` 状态。

新增 `POST /api/reviews/{run_id}`，动作支持 `approve`、`edit`、`reject`。

## 安全边界

- 没有知识库证据时不生成已完成回答；
- Citation 来源经过确定性集合校验；
- Reranker 超时或格式异常自动回退并触发低置信度审核；
- 人工审核使用内存 Checkpointer，服务重启后未完成审核状态会丢失。

## Demo

1. 提问“如何重置密码”，验证回答完成并显示 Citation；
2. 重复同一问题，验证 Redis 缓存避免重复模型调用；
3. 提问退款、法律或删除账户问题，验证状态为 `waiting_review`；
4. 在审核控件中编辑并批准，验证 Graph 恢复为 `completed`；
5. 模拟 Reranker 失败，验证回退 RRF 并进入审核。

## 已知限制

- 当前回答生成采用知识文档摘录组合，优先保证 Grounding，不追求自然语言润色；
- Checkpoint 使用 `InMemorySaver`，不支持重启恢复或多实例共享；
- 审核界面为基础演示能力，没有登录、权限、分配、分页或 SLA；
- LLM Reranker P95 约 15 秒，后续应替换为专用快速重排模型。
