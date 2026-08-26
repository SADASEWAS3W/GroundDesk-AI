# 与开发者 B 的二次开发对齐事项

## 1. 文档目的

本文档用于开发者 A 与开发者 B 在继续二次开发前确认共享接口、模块边界、路由规则和联调方式，避免双方基于未验证的假设并行开发。

本文档记录的是待讨论和待确认事项，不代表相关接口已经被开发者 B 接受，也不代表对应功能已经完成。

### 1.1 项目决策方授权

项目决策方已明确授权：后续开发默认开发者 B 接受开发者 A 侧确定的接口、数据结构、路由规则和实现方案，不再以取得开发者 B 的单独确认为开工或继续开发的前置条件。

因此，本文后续的“需要确认”事项改为开发者 A 的决策与通知清单：

- 开发者 A 可以根据仓库规则和现有代码证据直接选择建议方案并继续实现；
- 触及 State、API、Citation、HITL、数据库迁移或共享文件时，仍需提前向项目决策方说明影响；
- 开发者 B 后续接入时，以仓库中已经提交并通过验证的契约为准；
- 如果发现开发者 B 的实际代码与已冻结契约冲突，应报告冲突并制定迁移或兼容方案，不得静默覆盖对方改动；
- 未提交文档、Mock 或本地方案仍不视为正式契约，只有进入仓库并完成相应验证后才可作为集成基线。

## 2. 当前已验证事实

截至当前仓库状态，可以从代码和本地工作区确认：

- 生产链路仍使用 OpenAI Agents SDK，通过 Function Tool 调用现有 Vector-only 知识库检索；
- 开发者 A 已在本地工作区新增检索领域模型、组件 Protocol 和 `FakeRetrievalService`；
- 新检索契约尚未接入生产 Agent、FastAPI 或 Web；
- 真实 `VectorRetriever`、BM25、RRF、Reranker 和 Retrieval Eval 尚未实现；
- 仓库中尚未看到 LangGraph、`SupportState`、Citation、Grounding Check 或 HITL 的实现；
- 开发者 A 的新增检索代码和报告当前尚未提交；
- 当前仓库和远端分支无法证明开发者 B 在其他机器或其他未推送分支上的实际进度。

开发者 B 应先补充自己的真实开发状态、分支位置和已修改文件，再安排共享边界的改动。

## 3. 必须确认的事项

### 3.1 开发者 B 的当前实现状态

需要开发者 B 确认：

1. 是否已经开始 LangGraph、API、Citation UI 或 HITL 的开发；
2. 代码位于哪个分支、提交或 Pull Request；
3. 当前已修改和计划修改哪些文件；
4. 是否正在修改以下共享或高冲突文件：
   - `api/main.py`；
   - `agent/customer_success_agent.py`；
   - `agent/prompts.py`；
   - `pyproject.toml` 和 `uv.lock`；
   - 数据库迁移；
   - 前后端公共类型；
5. 哪些功能已经通过实际测试，哪些仍只是设计或 Mock。

确认结果：

```text
B 当前分支/PR：
B 已完成内容：
B 正在修改的文件：
B 计划修改的共享文件：
B 已执行的测试：
```

### 3.2 是否接受统一检索入口

开发者 A 当前提供的统一入口为：

```python
await retrieval_service.retrieve(
    rewritten_query,
    strategy="hybrid_rerank",
    top_k=3,
)
```

需要确认：

- LangGraph 是否只依赖 `RetrievalService` Protocol；
- B 是否接受 `vector_only`、`hybrid`、`hybrid_rerank` 三个策略名；
- 默认最终返回数量是否为 Top 3；
- Graph 节点是否禁止直接调用具体的 Vector、BM25 或 Reranker 实现；
- 配置错误是否保持快速失败，而无结果是否返回结构化低置信度结果。

建议方案：B 只依赖 `RetrievalService`，具体实现由服务端组合根注入。

确认结果：

```text
[ ] 接受当前方案
[ ] 需要修改
修改内容和原因：
```

### 3.3 RetrievalResult 如何进入 SupportState

当前检索层返回 `RetrievalResult` dataclass，但 LangGraph State 的最终结构尚未确定。

必须确定：

- State 保存 dataclass，还是只保存可序列化的纯字典；
- 如果保存字典，由 A 提供 `to_dict()`，还是由 B 在 Graph 边界转换；
- 是否需要支持 LangGraph Checkpointer 序列化；
- 检索文档写入 `retrieved_documents`、`reranked_documents`，还是统一的 `evidence_documents`；
- `low_confidence` 和 `confidence_reasons` 在 State 中映射到哪些字段。

建议方案：State 使用纯字典；检索层提供明确序列化边界；保留检索失败原因，不与 Grounding 失败原因混为同一字段。

建议字段：

```python
class SupportState(TypedDict, total=False):
    original_query: str
    rewritten_query: str
    evidence_documents: list[dict]
    retrieval_low_confidence: bool
    retrieval_issues: list[str]
    answer: str
    citations: list[dict]
    grounded: bool
    grounding_issues: list[str]
    requires_human_review: bool
    status: str
```

确认结果：

```text
State 存储形式：
文档字段名：
低置信度字段名：
序列化责任人：
```

### 3.4 Citation 的生成和校验边界

建议责任划分：

- A 提供最终证据文档及稳定的 `document_id`、`title`、`content` 和 `final_rank`；
- B 根据最终文档生成 Citation 编号和展示片段；
- B 校验回答引用的每个文档 ID 都属于本次最终证据集合；
- A 保证 Reranker 只能重排候选文档，不能引入新的文档 ID；
- Web 只展示 API 返回的结构化 Citation，不从回答文本自行猜测来源。

需要进一步确认：

- Citation 的 `excerpt` 由检索层裁剪，还是由生成节点提取；
- 回答中的 `[1]` 是否必须与 Citation 数组的 `index` 一一对应；
- 模型返回未知、重复或未使用的 Citation 时如何处理；
- Citation 校验失败是重新生成，还是直接进入人工审核；
- Citation 是否需要暴露分类、来源 URL 或额外 metadata。

建议方案：B 负责 excerpt 和编号；未知 Citation 直接判定 Grounding 失败并进入人工审核，基础版不自动多次重试。

确认结果：

```text
Excerpt 责任人：
无效 Citation 处理：
公开 Citation 字段：
```

### 3.5 低置信度、Grounding 和 HITL 路由

必须共同确定进入人工审核的确定性规则及优先级。

基础规则建议为：

1. 没有检索结果，进入人工审核；
2. 检索结果被标记为低置信度，进入人工审核；
3. 回答没有 Citation 或 Citation 越界，进入人工审核；
4. Grounding Check 发现无来源陈述，进入人工审核；
5. 退款、法律、删除账户等高风险请求，进入人工审核；
6. Reranker 降级时记录诊断信息，是否进入人工审核由共同确认的规则决定。

还需确认：

- 高风险规则由确定性代码还是模型判断；
- Query Rewrite 失败时使用原 Query 继续，还是进入人工审核；
- Retrieval Service 异常与“正常无结果”是否采用不同状态；
- Grounding Check 的输入和输出字段；
- 人工拒绝后最终状态和用户可见响应；
- 人工编辑并批准后是否再次执行 Citation/Grounding 校验。

建议方案：高风险分类至少包含确定性规则；系统异常标为 `failed`，正常低置信度标为 `waiting_review`；人工编辑后的答案再次执行 Citation 校验。

确认结果：

```text
waiting_review 条件：
failed 条件：
Reranker 降级处理：
批准后的重新校验规则：
拒绝后的最终状态：
```

### 3.6 LangGraph 结构和依赖注入位置

需要 B 确认最小 Graph 是否保持以下节点：

```text
rewrite_query
retrieve
rerank
generate
grounding_check
human_review
finish
```

同时确认：

- Retrieval Service 在 Graph 构造时注入、通过 runtime config 注入，还是放入服务端上下文；
- 节点内部不得创建数据库连接或模型客户端；
- 基础版是否使用 `InMemorySaver`；
- `thread_id`、`run_id` 和 `conversation_id` 的关系；
- Interrupt 恢复所需的最小输入结构；
- 旧 `run_agent()` 入口保留多久，如何回退。

建议方案：基础设施由 API lifespan/组合根创建，Graph 构造函数接收抽象依赖；基础版先使用 `InMemorySaver`；旧 Agent 入口保留为短期可配置回退。

确认结果：

```text
Retrieval Service 注入位置：
Checkpointer：
运行 ID 规则：
旧入口回退方案：
```

### 3.7 API Request/Response 和状态枚举

现有 API 主要返回 `job_id`、`correlation_id` 和纯文本 `response`，不能承载 Citation 和人工审核状态。

需要共同确定新的响应字段：

```text
run_id
conversation_id
status
answer
citations
requires_human_review
retrieval_issues
grounding_issues
error
retry_after
```

必须确认：

- `job_id` 与 `run_id` 是否合并；
- 是否继续保留 `correlation_id`；
- 状态枚举的唯一权威定义；
- 同步和异步 Chat API 是否返回同一业务结构；
- `waiting_review` 时 `answer` 是否只作为内部草稿，不直接展示给最终用户；
- 旧前端在迁移期间是否需要兼容旧字段；
- Review API 的路径、请求体和幂等行为。

建议状态最少包括：

```text
processing
completed
waiting_review
rejected
failed
```

任何 API 字段变化必须同步更新：

- 后端 Pydantic 模型；
- 前端 TypeScript 类型；
- `web/src/lib/api.ts`；
- 后端 API 测试；
- 前端集成测试；
- API 示例文档。

确认结果：

```text
ID 规则：
状态枚举：
Chat Response：
Review API：
向后兼容要求：
```

### 3.8 人工审核的数据保存边界

基础版计划使用 LangGraph `InMemorySaver`，但待审核列表和详情页需要能够查询等待中的任务。

需要确认：

- 待审核记录只存在 Checkpointer，还是同步写入 PostgreSQL；
- 如果只用内存，API 如何列出全部待审核任务；
- 服务重启后状态丢失是否接受为演示限制；
- 多进程或多实例部署是否明确不在基础版范围；
- 是否需要数据库迁移；
- 若需要迁移，由谁负责、如何回滚。

建议方案：先明确演示部署为单实例；如 `InMemorySaver` 无法可靠支持列表查询，则单独定义最小 Review Repository，不在未确认前直接新增数据库表。

确认结果：

```text
审核记录存储：
是否需要迁移：
服务重启限制：
责任人：
```

### 3.9 测试、Eval 和联合验收责任

需要确定双方提供的 Fake、测试数据和验收命令。

建议责任划分：

- A：检索模型、Vector、BM25、RRF、Reranker、Retrieval Service 和 Retrieval Eval；
- B：Graph 节点、路由、Citation、Grounding、HITL、API、Web 和 Agent Eval；
- 共同：约 30 条 Eval 数据标注、阈值选择、两条核心 Demo 和端到端验证。

需要确认：

- B 使用哪些固定 Query 和 Fake 文档进行 Graph 测试；
- A 的低置信度原因哪些会被 B 的路由测试覆盖；
- Citation ID 越界、空检索和高风险问题的测试归属；
- 联调测试使用 Fake、Mock PostgreSQL，还是真实 Compose 环境；
- 合并前必须执行哪些专项检查；
- 评测数据的审核和版本管理方式。

确认结果：

```text
A 测试责任：
B 测试责任：
共同验收命令：
Eval 数据负责人：
联调环境：
```

### 3.10 分支、提交和共享文件协调

双方必须确认：

- 各自开发分支及合并顺序；
- 第一次接口冻结对应的提交；
- 修改公共契约前必须通知另一方；
- 不同时修改 `api/main.py`、`agent/customer_success_agent.py`、`agent/prompts.py` 或同一个迁移文件；
- 依赖文件由谁统一修改；
- 每个 PR 的 Review 人和联调时间。

建议合并顺序：

1. A 提交检索契约和 Fake Service；
2. B 基于该提交完成最小 Graph；
3. A 提交真实 Vector Retriever；
4. 双方完成第一次 Vector-only 联调；
5. A 再依次加入 BM25、RRF 和 Reranker；
6. B 再接入 Citation、Grounding、HITL、API 和 Web 闭环。

确认结果：

```text
A 分支：
B 分支：
接口冻结提交：
依赖文件负责人：
首次联调时间：
PR Review 人：
```

## 4. 建议第一次联调的最小范围

第一次联调只验证以下闭环：

```text
用户 Query
→ Query Rewrite
→ FakeRetrievalService
→ 生成带结构化 Citation 的回答
→ 路由到 completed 或 waiting_review
→ API 返回统一状态
```

第一次联调暂不包含：

- 真实 BM25；
- RRF；
- 真实 Reranker；
- 数据库持久化 Checkpointer；
- 完整审核 UI；
- 生产级多实例部署。

最小验收场景：

1. Fake 返回有效文档，Graph 状态为 `completed`；
2. Fake 返回空结果，Graph 状态为 `waiting_review`；
3. 回答 Citation 只引用 Fake 返回的文档 ID；
4. 未审批的草稿不会作为最终答案返回用户；
5. API 和前端类型对同一状态和字段有一致定义。

## 5. 未确认前的停止边界

在上述公共事项未确认前：

- A 可以继续实现不改变公共契约的真实 Vector Retriever 和内部测试；
- B 可以使用当前 Fake Service 编写 Graph 的独立节点测试；
- 双方不得单方面固化 State、HTTP Response、Citation 或 Review 数据库结构；
- 不应以 Mock 可运行推断真实 LangGraph 已接入；
- 不应以文档中的建议方案推断另一方已经接受；
- 触及共享文件或数据库迁移前必须再次通知对方。

## 6. 对齐会议最终记录

完成讨论后填写：

```text
确认日期：
参与人：

已确认事项：
1.
2.
3.

暂缓事项：
1.
2.

需要补充验证的事项：
1.
2.

A 下一步：
B 下一步：
首次联调时间：
接口冻结提交或文档版本：
```

只有在双方填写并确认上述记录后，才能将对应建议标记为正式公共契约。
