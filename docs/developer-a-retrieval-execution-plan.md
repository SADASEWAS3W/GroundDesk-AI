# 开发者 A：AI 检索与评测分步执行方案

## 1. 目标

本方案用于分步骤完成项目中的 AI 检索与评测能力，范围包括：

- PostgreSQL/pgvector 向量检索；
- 基于 `rank-bm25` 的 BM25 关键词检索；
- RRF 多路召回融合；
- 可替换的 Reranker；
- 检索置信度信号；
- Retrieval Eval 数据集、指标和报告；
- Vector-only、Hybrid、Hybrid + Reranker 三种策略对比。

目标检索链路如下：

```text
改写后的 Query
       │
       ├── pgvector Top 10 ──┐
       │                     ├── RRF ── Reranker ── Final Top 3
       └── BM25 Top 10 ──────┘
```

本方案不负责 LangGraph 主流程、Query Rewrite、回答生成、Grounding、HITL 和 Citation UI。检索模块只向这些功能提供稳定的结果结构、引用来源和置信度信号。

## 2. 总体执行原则

1. 先固定公共接口，再实现具体算法。
2. 每个阶段都可以独立测试、提交和回退。
3. Vector、BM25、RRF、Reranker 保持独立，不把全部逻辑写进一个文件。
4. 查询和知识库文档统一使用 `text-embedding-v4`，向量维度固定为 1536。
5. 不直接相加向量分数和 BM25 原始分数，统一通过 RRF 使用排名融合。
6. Reranker 故障时自动降级为 RRF 结果，不能阻断整个客服流程。
7. 阈值必须由 Eval 结果确定，不提前凭经验写死。
8. 自动化测试不调用真实大模型，使用 Fake 或 Mock 实现。

## 3. 计划目录

```text
agent/
└── retrieval/
    ├── __init__.py
    ├── models.py
    ├── protocols.py
    ├── tokenizer.py
    ├── vector.py
    ├── bm25.py
    ├── fusion.py
    ├── reranker.py
    └── service.py

evals/
├── datasets/
│   └── retrieval_v1.jsonl
├── metrics.py
├── retrieval_eval.py
└── reports/

tests/
└── test_retrieval/
    ├── test_models.py
    ├── test_tokenizer.py
    ├── test_vector.py
    ├── test_bm25.py
    ├── test_fusion.py
    ├── test_reranker.py
    ├── test_service.py
    └── test_metrics.py
```

实际执行时先检查现有项目结构。如果已有同类模块，应优先复用或迁移，避免生成两套检索实现。

## 4. 阶段一：现状盘点与基线冻结

### 4.1 目标

确认当前知识库、Embedding、pgvector 查询和 Agent 调用路径，保存改造前的 Vector-only 基线。

### 4.2 操作清单

- 找到当前知识库表、ORM 模型和数据库迁移；
- 确认向量列确实为 `VECTOR(1536)`；
- 找到当前文档入库和 Query Embedding 代码；
- 确认两者使用相同的 Embedding 模型和维度；
- 找到现有 Vector-only 检索入口及调用方；
- 记录当前 Top K、距离函数、过滤条件和排序方向；
- 选取 5～10 个代表性问题，记录当前 Top 3 结果；
- 检查知识文档是否有稳定的 `document_id`、标题和正文。

### 4.3 产物

- 当前检索调用链说明；
- Vector-only 基线结果；
- 待复用代码和待替换代码清单；
- 已确认的数据库与 Embedding 契约。

### 4.4 完成标准

- 能说明一次用户查询如何到达 pgvector；
- 能独立运行一次现有检索；
- 确认分数是“越大越好”还是“越小越好”；
- 后续改造有可对比的基线结果。

### 4.5 建议提交

本阶段原则上只做调查和文档记录；如不修改仓库，则不提交。

## 5. 阶段二：固定接口、数据结构和 Mock

### 5.1 目标

先让开发者 A 和开发者 B 对接稳定接口，使 LangGraph 可以在真实检索完成前使用 Mock 联调。

### 5.2 核心数据结构

建议检索文档至少包含：

```python
@dataclass
class RetrievedDocument:
    document_id: str
    title: str
    content: str
    category: str | None
    metadata: dict[str, Any]
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    final_rank: int | None = None
```

统一结果至少包含：

```python
@dataclass
class RetrievalResult:
    query: str
    documents: list[RetrievedDocument]
    strategy: str
    low_confidence: bool
    confidence_reasons: list[str]
    diagnostics: dict[str, Any]
```

统一入口建议为异步接口：

```python
async def retrieve(
    query: str,
    *,
    strategy: str = "hybrid_rerank",
    top_k: int = 3,
) -> RetrievalResult:
    ...
```

### 5.3 操作清单

- 建立 `models.py`；
- 建立 VectorRetriever、KeywordRetriever、FusionStrategy、Reranker 的 Protocol；
- 规定空 Query、无结果和组件异常的行为；
- 规定所有上层可比较分数均为“越大越相关”；
- 定义 `FakeRetrievalService`，返回固定文档；
- 与开发者 B 确认 `SupportState` 如何接收检索结果；
- 明确 Citation 边界：A 提供引用来源，B 负责回答中的编号和展示。

### 5.4 测试

- 数据结构序列化测试；
- Fake Service 返回顺序测试；
- 空结果测试；
-非法 `strategy` 测试；
- Top K 边界测试。

### 5.5 完成标准

- 开发者 B 只依赖统一入口，不直接调用 Vector 或 BM25；
- Mock 可以接入 LangGraph；
- 后续替换真实检索时不需要修改公共接口。

### 5.6 建议提交

```text
feat(retrieval): define retrieval contracts and fake service
```

## 6. 阶段三：实现 Vector Retriever

### 6.1 目标

把现有 pgvector 查询封装成独立组件，并保持改造前行为可对比。

### 6.2 操作清单

- 抽取或复用现有 Query Embedding 调用；
- 校验返回向量维度为 1536；
- 使用参数化 SQL 或现有 ORM 查询，避免拼接用户输入；
- 默认获取 Top 10 候选；
- 返回稳定的 `document_id` 和文档元数据；
- 保存原始距离、转换后的相似度和 `vector_rank`；
- 记录 Embedding 耗时和数据库查询耗时；
- 明确外部模型或数据库异常类型。

### 6.3 测试

- Mock Embedding 下的排序测试；
- 1536 维校验测试；
- 空知识库测试；
- 数据库异常测试；
- Top K 测试；
- PostgreSQL/pgvector 集成测试。

### 6.4 完成标准

- 新 Vector Retriever 与原 Vector-only 结果基本一致；
- 返回字段满足阶段二的契约；
- 单元测试不调用真实通义千问 API；
- 集成测试能在本地 PostgreSQL 中返回 Top 10。

### 6.5 建议提交

```text
feat(retrieval): add pgvector retriever
```

## 7. 阶段四：实现 BM25 和 RRF

### 7.1 目标

建立第二条关键词召回链路，并通过排名融合获得 Hybrid 候选。

### 7.2 BM25 操作清单

- 增加 `rank-bm25` 依赖；
- 建立可替换 Tokenizer；
- 中文采用中文分词，英文统一小写并按词切分；
- Query 和 Document 使用同一套标准化规则；
- 应用启动时从 PostgreSQL 加载知识文档；
- 建立文档 ID 与 BM25 语料下标的稳定映射；
- 提供 `build()`、`search()`、`rebuild()` 和状态查询；
- 对空语料、空 Query 和索引未构建提供明确行为。

### 7.3 RRF 操作清单

- 使用公式 `1 / (k + rank)` 计算每一路贡献；
- `k` 配置化，初始值可以使用 60，但最终由评测确认；
- 使用 `document_id` 合并重复文档；
- 保留 Vector、BM25 的原始排名和分数；
- 记录文档来自哪个召回器；
- 对同分结果设置稳定的次级排序规则。

### 7.4 测试

- 中文、英文、中英混合文本分词；
- 标点、空白和大小写处理；
- BM25 空索引和重建；
- 两路都命中同一文档时正确去重；
- 只被一路命中的文档仍能进入结果；
- RRF 公式和稳定排序；
- BM25 Top 10、Vector Top 10、Hybrid 候选数量。

### 7.5 完成标准

- Vector 和 BM25 可以独立运行；
- Hybrid 通过统一 Service 返回；
- 不直接相加两个召回器的原始分数；
- 重新构建 BM25 索引后可以检索新增文档。

### 7.6 已知限制

MVP 阶段 BM25 索引保存在单个应用进程内：

- 应用重启后需要重新构建；
- 知识库变化后需要手动或通过管理接口重建；
- 多进程部署时每个进程分别持有索引；
- 暂不保证数据库与 BM25 索引实时同步。

### 7.7 建议提交

```text
feat(retrieval): add bm25 retrieval and rrf fusion
```

## 8. 阶段五：实现 Reranker 和安全降级

### 8.1 目标

对 RRF 候选进行语义重排，选出最终 Top 3，同时保证模型失败时系统仍可用。

### 8.2 操作清单

- 建立可替换的 `Reranker` 接口；
- 建立 `NoOpReranker`；
- 实现首个真实 Reranker；
- 限制输入候选数量和单篇文档长度；
- 设置超时；
- 校验模型返回的文档 ID 必须属于本次候选；
- 丢弃重复或未知文档 ID；
- 模型异常、超时或格式错误时回退到 RRF 排序；
- 输出 `rerank_score`、`final_rank` 和降级原因；
- 最终只返回配置数量的文档，默认 Top 3。

### 8.3 测试

- 正常重排；
- 同分稳定排序；
- 未知文档 ID；
- 重复文档 ID；
- 返回字段缺失；
- 超时和异常降级；
- 候选少于 Top K；
- 不允许 Reranker 引入候选集合之外的 Citation 来源。

### 8.4 完成标准

- `hybrid_rerank` 能返回最终 Top 3；
- Reranker 故障不会导致完整请求失败；
- 降级信息可从 `diagnostics` 中看到；
- 测试使用 Fake Reranker，可重复且不产生 API 成本。

### 8.5 建议提交

```text
feat(retrieval): add pluggable reranker with fallback
```

## 9. 阶段六：建立 Retrieval Eval

### 9.1 目标

用同一份标注数据定量比较三种策略，为 Top K、RRF 参数和置信度阈值提供依据。

### 9.2 数据集

第一版准备约 30 条 JSONL 数据：

```json
{
  "id": "refund-001",
  "query": "退款什么时候到账？",
  "relevant_document_ids": ["refund-policy"],
  "tags": ["refund", "normal"],
  "notes": "退款到账时间"
}
```

样本应覆盖：

- 正常提问；
- 口语和错别字；
- 中英文混合；
- 同义改写；
- 多文档相关；
- 信息不足；
- 知识库没有答案；
- 容易被关键词误导的问题。

建议先使用 20 条调参集和 10 条保留验证集。数据量较小，因此报告中需要注明指标波动风险。

### 9.3 指标

必须实现：

- Recall@3；
- MRR。

建议同时输出：

- Recall@10；
- 无召回率；
- P50/P95 检索耗时；
- Reranker 降级次数；
- 每阶段候选数量。

### 9.4 对比实验

在相同数据集上运行：

1. `vector_only`；
2. `hybrid`；
3. `hybrid_rerank`。

输出汇总表和失败明细。失败明细至少包括：

- Query；
- 标准相关文档；
- 实际 Top 3；
- Vector、BM25、RRF、Reranker 各阶段排名；
- 初步失败分类。

### 9.5 失败分类

建议统一分为：

- Embedding 召回失败；
- BM25 分词或关键词召回失败；
- RRF 融合后被挤出；
- Reranker 错排；
- 标注不完整或存在歧义；
- 知识库缺少答案；
- 文档切分粒度不合适。

### 9.6 测试

- Recall@3 手工样例；
- MRR 手工样例；
- 多个相关文档；
- 没有相关文档；
- 空预测结果；
- 报告生成结果可重复。

### 9.7 完成标准

- 一个命令可以运行三种策略；
- 指标由脚本生成，不手工填写；
- 报告能定位到具体失败 Query；
- 真实 API Key 缺失时可以明确提示或运行离线 Fake 模式。

### 9.8 建议提交

```text
feat(evals): add retrieval benchmark and metrics
```

## 10. 阶段七：调参与置信度校准

### 10.1 目标

在调参集上优化检索参数，在保留集上确认效果，并向 Agent 输出可解释的低置信度结果。

### 10.2 调整参数

- Vector 候选 Top K；
- BM25 候选 Top K；
- RRF 的 `k`；
- 进入 Reranker 的候选数量；
- 最终返回数量；
- Reranker 超时；
- 文档截断长度。

每次只调整一组参数并记录结果，不同时修改多个变量后只保留最终数字。

### 10.3 置信度信号

先记录信号，再通过评测确定阈值：

- 是否完全无结果；
- Top 1 Reranker 分数；
- Top 1 与 Top 2 的分差；
- Top 3 最低分；
- Vector 和 BM25 是否共同命中；
- 是否发生 Reranker 降级；
- 高质量候选文档数量。

建议输出可解释原因：

```text
no_retrieval_results
top1_score_below_threshold
small_top1_top2_margin
single_retriever_match
reranker_fallback
```

### 10.4 完成标准

- 阈值对应明确的评测记录；
- 保留验证集没有明显退化；
- 低置信度结果能被开发者 B 用于 HITL 路由；
- 配置有默认值，并可通过项目配置覆盖。

### 10.5 建议提交

```text
feat(retrieval): calibrate retrieval confidence signals
```

## 11. 联合接入和最终验收

### 11.1 与开发者 B 的接口检查

- LangGraph 使用 `rewritten_query` 调用统一检索入口；
- 检索结果可以写入 `retrieved_documents` 或约定后的统一字段；
- 回答生成只使用本次返回的最终文档；
- Citation 的文档 ID 只能来自本次最终结果；
- `low_confidence` 可以触发人工审核；
- Reranker 降级时流程仍能完成或进入人工审核。

### 11.2 最终验收场景

至少演示：

1. 语义相近但关键词不同，Vector 检索成功；
2. 包含精确产品名或错误码，BM25 改善召回；
3. 两路召回重复文档，RRF 正确合并；
4. Reranker 改善 Top 3 排序；
5. Reranker 故障，系统自动降级；
6. 知识库没有答案，返回低置信度；
7. Citation ID 全部属于本次最终 Top 3；
8. 三种策略评测报告可以重复生成。

### 11.3 总体验收标准

- Vector、BM25、RRF、Reranker 都有独立接口和测试；
- 使用固定 1536 维 Embedding 契约；
- 能运行三种检索策略；
- 自动计算 Recall@3 和 MRR；
- 具有失败分析报告；
- Reranker 具有超时和回退；
- 置信度阈值来自 Eval；
- 检索模块可以脱离 LangGraph 独立测试；
- 不泄露 API Key，测试和日志中不输出敏感配置。

## 12. 推荐执行节奏

| 工作日 | 工作内容 | 当日可验收结果 |
|---|---|---|
| 第 1 天 | 阶段一、阶段二 | 基线、数据契约、Mock Service |
| 第 2 天 | Vector Retriever | pgvector Top 10 和测试 |
| 第 3 天 | BM25、Tokenizer | BM25 Top 10 和索引重建 |
| 第 4 天 | RRF、统一 Service | Hybrid 检索可运行 |
| 第 5 天 | Reranker、降级 | Hybrid + Reranker Top 3 |
| 第 6 天 | Eval 数据和指标 | 三策略初始对比报告 |
| 第 7 天 | 调参、失败分析、联调 | 阈值、最终报告和联合验收 |

时间是建议值。每完成一个阶段先运行对应测试并提交，再进入下一阶段。如果某阶段验收失败，应留在当前阶段修复，不将未完成问题带入下一阶段。

## 13. 每一步的固定执行模板

后续逐步实施时，每个阶段都按以下顺序进行：

1. 检查当前分支和未提交改动；
2. 阅读阶段涉及的现有代码；
3. 写出本阶段预计修改的文件清单；
4. 实现最小功能；
5. 增加单元测试；
6. 运行相关测试和静态检查；
7. 展示修改摘要和测试结果；
8. 用户确认后提交；
9. 再进入下一阶段。

每个提交或 Pull Request 说明应包含：

```text
完成内容：
未完成内容：
接口变化：
验证方式：
评测结果：
已知限制：
```

## 14. 第一步建议

正式编码时先执行“阶段一：现状盘点与基线冻结”。这一步只检查代码和运行现有检索，不重构、不增加依赖、不修改公共接口。完成后先输出：

- 当前检索调用链；
- 当前数据库与 Embedding 契约；
- 当前 Vector-only 基线；
- 下一阶段预计新增和修改的文件。

确认这些信息后，再开始阶段二的接口实现。
