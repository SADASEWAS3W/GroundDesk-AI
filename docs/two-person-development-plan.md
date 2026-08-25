# AI 客服项目双人开发分工文档（基础版）

## 1. 目标与范围

两人基于现有 Next.js、FastAPI、PostgreSQL/pgvector 和 Redis 项目，完成一个可以稳定演示、方便后续扩展的 AI 客服基础版。

基础版必须包含：

1. LangGraph 基础工作流；
2. Hybrid Retrieval；
3. Reranker；
4. Citation；
5. Grounding Check；
6. Human-in-the-loop；
7. 基础 Evaluation。

本阶段以“核心流程跑通”为目标，不追求生产级细节。

## 2. 本阶段不做

- Multi-Agent、MCP、Kafka；
- 微服务拆分和新向量数据库；
- 长期 Vector Memory 和模型微调；
- Kubernetes 深度优化；
- 完整登录、RBAC 和多租户；
- Gmail、WhatsApp 真实出站；
- 生产级任务队列；
- 完整知识库 CMS 和运营 Dashboard；
- 完整可观测平台和大规模压测。

## 3. 人员分工

### 3.1 开发者 A：AI 检索与评测

负责：

- 实现 pgvector 向量检索；
- 使用 `rank-bm25` 实现 BM25 关键词检索；
- 使用 RRF 合并两路结果；
- 接入基础 Reranker；
- 设计检索结果和相关性分数的数据结构；
- 编写 Retrieval Eval；
- 对比 Vector-only、Hybrid、Hybrid + Reranker；
- 分析召回失败案例并调整检索参数。

主要目录：

```text
retrieval/
evals/
tests/test_retrieval/
```

### 3.2 开发者 B：AI Agent 与全栈交互

负责：

- 搭建 LangGraph 状态图和条件路由；
- 实现简化版 Query Rewrite；
- 根据检索上下文生成结构化 Citation；
- 实现 Grounding Check；
- 实现 Human-in-the-loop 暂停与恢复；
- 编写 Agent Eval 和升级准确率评测；
- 接入 LangGraph 统一 API 入口；
- 实现对话和运行状态 API；
- 实现待审核列表、批准和拒绝 API；
- 在聊天页面展示 Citation；
- 实现待审核列表和审核详情页；
- 支持编辑、批准和拒绝 AI 草稿；
- 补充基础输入校验和错误处理；
- 编写 API、前端和关键流程测试；
- 更新 README 和演示说明。

主要目录：

```text
api/
agent/
web/
tests/test_api/
tests/test_agent/
web/src/__tests__/
docs/
```

### 3.3 共同负责

- 确认公共 State 和 API Contract；
- 标注 Eval 数据；
- 共同确定 Reranker、Grounding 和人工升级阈值；
- 联调两条核心演示流程；
- 相互 Code Review；
- 完成最终测试和 Demo。

## 4. 基础工作流

```text
用户问题
   ↓
Query Rewrite
   ↓
Hybrid Retrieval（pgvector + BM25）
   ↓
Reranker
   ↓
生成带 Citation 的回答
   ↓
Grounding Check
   ├── 通过 → 返回用户
   └── 失败 → 等待人工审核
                    ↓
              编辑并批准/拒绝
```

LangGraph 只实现以下节点：

```text
rewrite_query
retrieve
rerank
generate
grounding_check
human_review
finish
```

不设计子图、并行节点和多 Agent 路由。

## 5. 最小公共接口

### 5.1 SupportState

```python
class SupportState(TypedDict, total=False):
    run_id: str
    conversation_id: str
    original_query: str
    rewritten_query: str
    retrieved_documents: list[dict]
    reranked_documents: list[dict]
    answer: str
    citations: list[dict]
    grounded: bool
    grounding_issues: list[str]
    status: str
    requires_human_review: bool
```

### 5.2 Citation

```python
class Citation(BaseModel):
    index: int
    document_id: str
    title: str
    excerpt: str
```

### 5.3 API 返回示例

```json
{
  "run_id": "run-id",
  "status": "completed",
  "answer": "回答内容 [1]",
  "citations": [
    {
      "index": 1,
      "document_id": "document-id",
      "title": "Password reset",
      "excerpt": "Open Settings and select..."
    }
  ],
  "requires_human_review": false
}
```

公共字段变化必须由两人共同确认。

## 6. 开发阶段

### 阶段一：接口与 LangGraph 骨架

预计时间：1–2 天。

开发者 A：

- 定义检索输入、文档结果和分数字段；
- 提供 Vector、BM25、RRF 和 Reranker 的 Mock 接口；
- 准备基础检索测试数据。

开发者 B：

- 定义 `SupportState`；
- 创建 LangGraph 节点和条件路由；
- 使用 A 提供的 Mock 检索接口跑通完整 Graph；
- 保留旧 Agent 入口作为临时回退；
- 定义 API Request/Response；
- 准备前端调用封装；
- 增加运行状态类型；
- 创建 Citation 和 Review 页面骨架。

验收：Graph 能进入 `completed` 或 `waiting_review`，前后端字段一致。

### 阶段二：Hybrid RAG 与 Citation

预计时间：2–3 天。

开发者 A：

- 使用 pgvector 完成语义召回 Top 10；
- 使用 `rank-bm25` 完成 BM25 关键词召回 Top 10；
- 使用 RRF 融合两路排名；
- 基础 Reranker 重排；
- 选择最终 Top 3；
- 生成 Citation。

开发者 B：

- 根据最终 Top 3 文档生成带引用回答；
- 保证 Citation ID 只能来自最终检索上下文；
- 接入新的结构化回答；
- 展示 `[1]`、`[2]` 引用；
- 实现可展开的引用卡片；
- 展示文档标题和引用片段。

验收：pgvector 和 BM25 两路检索均可运行，RRF 能融合两路排名，回答中的引用能映射到真实知识库文档。

### 阶段三：Grounding 与人工审核

预计时间：2–3 天。

开发者 A：

- 向 Agent 提供检索结果、相关性分数和低置信度标记；
- 构造无结果、弱相关和错误召回测试样本；
- 验证检索失败时是否正确进入人工审核。

开发者 B：

- 实现 Grounding Check；
- 检查回答是否包含有效 Citation；
- 实现高风险问题路由；
- 使用 LangGraph Interrupt 暂停工作流；
- 提供批准、修改和拒绝后的恢复方法；
- 实现待审核列表和审核详情；
- 展示问题、AI 草稿、失败原因和引用；
- 支持编辑、Approve 和 Reject；
- 审核完成后刷新运行状态。

基础版进入人工审核的条件：

1. 没有检索到知识库文档；
2. 回答没有 Citation 或 Citation 无效；
3. 请求属于退款、法律或删除账户等高风险类型。

验收：未审批答案不会直接返回用户，人工批准后流程可以完成。

### 阶段四：基础 Evaluation 与联调

预计时间：2 天。

开发者 A：

- 编写 Retrieval Eval 脚本；
- 对比 Vector-only、Hybrid、Hybrid + Reranker；
- 输出 Recall@3 和 MRR 结果；
- 分析检索失败案例。

开发者 B：

- 共同标注约 30 条测试问题；
- 编写 Agent Eval；
- 统计 Grounded Answer Rate 和 Correct Escalation Rate；
- 统计端到端 P95 Latency；
- 补充 API 和前端测试；
- 编写 Demo 步骤；
- 更新 README。

基础版只统计：

- Recall@3；
- MRR；
- Grounded Answer Rate；
- Correct Escalation Rate；
- P95 Latency。

验收：评测可通过一条命令运行，结果由脚本生成，不手工编写指标。

## 7. 允许采用的简化方案

### Checkpoint

先使用 LangGraph `InMemorySaver`，保证暂停和恢复能够演示。服务重启后状态丢失属于已知限制，后续再替换成 PostgreSQL Checkpointer。

### Reranker

可以先使用轻量 Cross-Encoder、LLM 结构化打分或可替换的相关性打分函数。基础版重点是存在独立重排步骤和统一接口。

### BM25

基础版使用 `rank-bm25` 在应用进程内构建 BM25 索引：

```text
知识库文档
   ├── pgvector 语义召回 Top 10
   └── rank-bm25 关键词召回 Top 10
                 ↓
              RRF 融合
                 ↓
              Reranker
                 ↓
              最终 Top 3
```

基础版在服务启动时从 PostgreSQL 读取知识库文档并构建 BM25 索引。知识库内容发生变化时，手动或通过管理接口重建索引。

已知限制：BM25 索引保存在单个应用进程内，服务重启需要重新构建，多实例之间也不会自动同步。后续如需生产化，可迁移到支持 BM25 的 PostgreSQL 扩展或独立搜索服务。

### Query Rewrite

只输出一个改写后的检索 Query，不做多查询扩展。

### Grounding Check

只检查文档、Citation 和模型报告的无来源陈述，不构建复杂规则引擎。

### 人工审核后台

只做待审核列表和审核详情两个页面，不做复杂筛选、分页、分配、权限和 SLA。

## 8. Git 协作规则

两人都会修改 AI 相关代码，但按模块划分边界：

```text
开发者 A：retrieval、BM25、RRF、Reranker、Retrieval Eval
开发者 B：graph、Query Rewrite、Generation、Grounding、HITL、Agent Eval
```

推荐将 `agent/` 拆分为独立模块，避免两人集中修改同一个文件：

```text
agent/
├── graph.py              # B
├── state.py              # B 主维护，公共变更共同确认
├── nodes/                # B
└── retrieval/            # A
    ├── vector.py
    ├── bm25.py
    ├── fusion.py
    └── reranker.py
```

建议分支：

```text
feat/a-langgraph-rag
feat/a-evaluation
feat/b-citation-ui
feat/b-human-review
```

以下文件不要同时修改：

- `api/main.py`；
- `agent/customer_success_agent.py`；
- `agent/prompts.py`；
- 同一个数据库迁移文件。

每个 Pull Request 必须说明：

```text
完成内容：
未完成内容：
接口变化：
验证方法：
已知限制：
```

合并前由另一人完成 Review，每两天至少集成一次。

## 9. 两条核心 Demo

### 正常回答

```text
用户询问如何重置密码
→ Query Rewrite
→ pgvector + BM25 Hybrid Retrieval
→ Reranker
→ 生成带 Citation 的回答
→ Grounding Check 通过
→ 前端展示答案和引用
```

### 人工审核

```text
用户提出退款或知识库外问题
→ 风险或 Grounding 检查失败
→ 状态变为 waiting_review
→ 审核后台展示草稿和原因
→ 人工编辑并批准
→ 工作流恢复并返回最终答案
```

两条流程稳定跑通，即可认为基础版完成。

## 10. 最终验收标准

- 使用 LangGraph 显式工作流；
- Hybrid Retrieval 使用 PostgreSQL/pgvector 语义召回和 `rank-bm25` 关键词召回；
- 检索结果经过 Reranker；
- 前端展示可查看的 Citation；
- Grounding Check 能阻止明显无依据回答；
- Human-in-the-loop 可以暂停、编辑和恢复；
- 至少有约 30 条 Eval 数据；
- 能对比三种检索方案；
- 后端和前端核心测试通过；
- README 明确基础版限制；
- 两条核心 Demo 可以稳定演示。

## 11. 后续完善方向

基础版完成后，再根据实际问题增加：

- PostgreSQL 持久化 Checkpoint；
- Cross-Encoder Reranker 调优；
- 更严格的 Grounding 评测；
- 完整多轮对话；
- 知识库管理页面；
- 登录和审核权限；
- AI Trace 与成本统计；
- 更大的 Eval 数据集；
- 生产级异步任务队列。

后续优化应由真实测试结果驱动，不在基础版阶段提前堆叠复杂度。

## 12. 两人的 AI 简历侧重点

开发者 A 可以描述：

> 负责 AI 客服系统的 Hybrid RAG，使用 pgvector 与 BM25 双路召回、RRF 排名融合和 Reranker 重排，并通过 Recall@3、MRR 和 Baseline 实验评估检索质量。

开发者 B 可以描述：

> 负责基于 LangGraph 的 AI Agent 工作流，实现 Query Rewrite、Citation、Grounding Check、Human-in-the-loop 暂停恢复及 Agent Evaluation，并完成 FastAPI 与 Next.js 交互闭环。

两人都参与 AI 核心功能，但侧重点分别是“检索质量”和“Agent 可靠性”，避免简历内容完全相同。
