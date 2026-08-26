# 开发者 A 阶段二报告：检索契约与 Fake Service

## 1. 执行结论

阶段二已经完成。项目新增了与模型供应商、数据库、FastAPI 和 LangGraph 解耦的检索领域模型、组件协议和 Fake Retrieval Service。现有 `search_knowledge_base` 生产链路未被修改。

开发者 B 现在可以只依赖 `RetrievalService.retrieve()` 接入 LangGraph，并在 Vector、BM25、RRF 和 Reranker 尚未完成时使用固定结果联调。

## 2. 新增文件

```text
agent/retrieval/__init__.py
agent/retrieval/models.py
agent/retrieval/protocols.py
agent/retrieval/service.py
tests/test_retrieval/__init__.py
tests/test_retrieval/test_models.py
tests/test_retrieval/test_service.py
```

本阶段没有修改：

```text
api/main.py
agent/customer_success_agent.py
agent/prompts.py
agent/tools/knowledge.py
database/migrations/
```

## 3. 已固定的公共契约

### 3.1 检索策略

当前统一支持以下策略名称：

```text
vector_only
hybrid
hybrid_rerank
```

未知策略会抛出带支持列表的 `ValueError`，不会静默回退到其他策略。

### 3.2 Top K

所有检索阶段统一约束：

```text
1 <= top_k <= 100
```

布尔值、浮点数、零、负数和超过上限的值都会被拒绝。

### 3.3 RetrievedDocument

稳定字段包括：

- `document_id`；
- `title`；
- `content`；
- `category`；
- `metadata`；
- `source_retrievers`；
- Vector、BM25、RRF、Reranker 各阶段分数；
- Vector、BM25 和最终排名。

公共约定：

- 文档 ID、标题和正文不能为空；
- 所有排名从 1 开始；
- 所有对上层暴露的分数都是越大越相关；
- 分数必须是有限数，拒绝 `NaN` 和正负无穷；
- 不要求每个文档拥有全部阶段的分数。

### 3.4 RetrievalResult

统一返回：

- 原始检索 Query；
- 最终文档列表；
- 实际使用的策略；
- `low_confidence`；
- 可解释的 `confidence_reasons`；
- 结构化 `RetrievalDiagnostics`。

当 `low_confidence=True` 时，至少必须提供一个原因。诊断中的 `returned_count` 必须与文档数量一致，避免流程状态和实际证据不一致。

### 3.5 Diagnostics

已预留以下诊断字段：

- Vector、BM25、融合和最终候选数量；
- Embedding、Vector、BM25、融合、重排和总耗时；
- Reranker 是否降级；
- 降级原因；
- 可扩展属性。

本阶段只定义结构，不伪造真实耗时和分数。

## 4. 独立组件协议

已经定义五个结构化接口：

```text
VectorRetriever.search()
BM25Retriever.search()
FusionStrategy.fuse()
Reranker.rerank()
RetrievalService.retrieve()
```

这些接口只接收 Query、候选文档和 Top K，不直接读取环境变量，也不创建数据库或模型客户端。真实实现将在组合根处通过依赖注入获得基础设施。

其中 Reranker 只能重排传入的候选集合，不能引入新的文档 ID，为后续 Citation 安全校验建立边界。

## 5. Fake Retrieval Service 行为

Fake Service 支持：

- 按标准化后的 Query 返回固定结果；
- 忽略 Query 大小写、首尾空白和重复空格；
- 为返回文档填写从 1 开始的 `final_rank`；
- 按 Top K 截断；
- 为未知 Query 返回默认文档或明确的空结果；
- 对空 Query 返回 `empty_query`；
- 对没有配置结果的 Query 返回 `no_retrieval_results`；
- 返回文档副本，防止调用方修改后污染下一次测试。

示例：

```python
from agent.retrieval import FakeRetrievalService, RetrievedDocument

password_doc = RetrievedDocument(
    document_id="password-reset",
    title="Password reset",
    content="Open Settings and select Reset Password.",
    category="account-management",
)

retrieval_service = FakeRetrievalService(
    {"reset my password": [password_doc]}
)

result = await retrieval_service.retrieve(
    "Reset   My Password",
    strategy="hybrid_rerank",
    top_k=3,
)
```

开发者 B 可以将 `RetrievalService` 作为构造参数或 Graph 运行依赖注入，不需要引用 `FakeRetrievalService` 的具体类型。

## 6. 空查询和失败行为

本阶段确定以下行为：

| 场景 | 行为 |
|---|---|
| Query 为空或只有空白 | 返回空文档、低置信度、原因 `empty_query` |
| Query 没有结果 | 返回空文档、低置信度、原因 `no_retrieval_results` |
| Strategy 未知 | 抛出 `ValueError` |
| Top K 非法 | 抛出 `TypeError` 或 `ValueError` |
| 结果被标记为低置信度但没有原因 | 构造结果失败 |
| 诊断数量与文档数量不一致 | 构造结果失败 |

输入配置错误采用快速失败；正常的“没有相关知识”采用结构化低置信度结果，方便 LangGraph 路由到人工审核。

## 7. 测试结果

### 7.1 后端

```text
217 passed
```

覆盖阶段二的新测试以及原有 Tool、Agent、Database、Cache 和 API 测试。

正式 Harness 在只读挂载仓库时产生一条 pytest 缓存写入警告，不影响测试结果。

### 7.2 前端

```text
11 test files passed
81 tests passed
```

前端测试输出包含已有的 React `act()` 和 Canvas 环境提示，没有测试失败。

`npm audit` 同时报告 14 个依赖漏洞（2 个低危、11 个高危、1 个严重）。本阶段没有修改前端依赖，未执行可能产生破坏性升级的 `npm audit fix --force`。

### 7.3 Harness 静态检查

以下检查通过：

- Secret 扫描；
- 架构边界；
- 1536 维 Embedding 契约；
- `git diff --check`。

### 7.4 Compose

统一 Harness 的 `verify-compose.ps1` 因文件现有中文编码问题产生 PowerShell ParserError。随后直接执行其对应检查，结果如下：

- `docker compose config --quiet` 通过；
- API、Web、PostgreSQL、Redis 共四个服务全部健康；
- API `/health` 返回 HTTP 200；
- Web 首页返回 HTTP 200。

该脚本编码问题不是本阶段引入，阶段二没有修改 Harness 文件。

## 8. 已知限制

- Fake Service 只用于联调和测试，不访问真实知识库；
- 真实 Vector Retriever 尚未迁移到新接口；
- 当前生产 Agent 尚未注入 `RetrievalService`；
- 置信度目前只表达空 Query 和无结果，不包含分数阈值；
- 当前协议是 Python 内部契约，不是 HTTP API 契约；
- 暂未增加序列化方法，LangGraph State 如需纯字典应在共享边界统一决定；
- 正式类型检查器尚未纳入项目门禁，Protocol 的静态兼容性主要依赖实现签名和测试。

## 9. 阶段三建议

下一阶段实现 `VectorRetriever` 的真实 pgvector 版本：

1. 复用 `AgentContext` 中注入的模型客户端和数据库连接池；
2. 从 Function Tool 中抽取 Embedding 和 SQL 查询，但暂时保留旧 Tool 入口；
3. 默认获取 Top 10 候选；
4. 返回 UUID、相似度、Vector Rank 和来源信息；
5. 添加 Mock 单元测试和 PostgreSQL 集成测试；
6. 对比新 Retriever 与阶段一 Vector-only 基线；
7. 确认无回归后，再决定旧 Function Tool 如何委托新 Service。

阶段三不应同时实现 BM25、RRF 或修改 LangGraph，以保持提交边界清晰。
