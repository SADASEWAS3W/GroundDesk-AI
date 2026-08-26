# 开发者 A 阶段四报告：BM25、Tokenizer、RRF 与 Hybrid Service

## 1. 执行结论

阶段四代码实现已经完成。项目新增中英文统一 Tokenizer、可完整重建的进程内 BM25 Retriever、Reciprocal Rank Fusion，以及组合 Vector 与 BM25 的 `HybridRetrievalService`。

当前统一 Service 可以执行：

```text
vector_only
hybrid
```

`hybrid_rerank` 仍属于阶段五。在真实 Reranker 接入前，该策略会抛出明确的 `RetrievalCapabilityError`，不会把 RRF 结果伪装成已经重排的结果。

现有生产 Agent 和 `search_knowledge_base` Function Tool 没有修改，因此生产流量仍走旧 Vector-only 路径。

## 2. 新增和修改内容

新增：

```text
agent/retrieval/tokenizer.py
agent/retrieval/bm25.py
agent/retrieval/fusion.py
tests/test_retrieval/test_tokenizer.py
tests/test_retrieval/test_bm25.py
tests/test_retrieval/test_fusion.py
tests/test_retrieval/test_hybrid_service.py
docs/developer-a-phase-4-bm25-rrf-report.md
```

修改：

```text
agent/retrieval/__init__.py
agent/retrieval/service.py
tests/test_retrieval/test_vector_pg_integration.py
pyproject.toml
uv.lock
```

新增运行依赖：

```text
jieba>=0.42.1
rank-bm25>=0.2.2
```

`numpy` 由 `rank-bm25` 间接引入。

## 3. Tokenizer

`BilingualTokenizer` 对 Query 和文档使用同一条标准化流程：

- 英文统一 `casefold`；
- 清除无意义标点和空白；
- 保留常见技术标识符中的点、下划线、加号、井号和连字符；
- 中文使用 `jieba` 精确模式分词；
- 中英文混合文本按片段分别处理；
- 空白输入返回空 Token 列表。

基础版暂未增加领域词典、停用词表或同义词扩展。后续应根据 Retrieval Eval 的失败案例决定是否增加这些规则。

## 4. BM25 Retriever

`InMemoryBM25Retriever` 当前提供：

```text
build()
rebuild()
search()
status
```

行为边界：

- 首次构建前调用搜索会抛出 `BM25IndexNotBuiltError`；
- 空语料构建成功，搜索返回空结果；
- 全部文档都没有有效 Token 时不会构造无效 BM25 索引；
- 空 Query 和无词项交集返回空结果；
- 拒绝重复 `document_id`；
- 重建时先生成完整新快照，再替换当前快照；
- 返回文档副本，调用方修改结果不会污染索引；
- 结果包含 `bm25_score`、从 1 开始的 `bm25_rank` 和 `source_retrievers`。

`load_knowledge_documents()` 从 PostgreSQL 一次性加载稳定 ID、标题、正文和分类，用于应用启动或手动重建索引。

## 5. RRF Fusion

`ReciprocalRankFusion` 使用：

```text
score(document) = Σ 1 / (k + rank)
```

当前默认：

```text
k = 60
```

该值目前只是可配置初始值，最终应由阶段六、阶段七的评测确认。

融合规则：

- 使用 `document_id` 合并两路结果；
- 不相加 Vector similarity 与 BM25 原始分数；
- 保留 Vector、BM25 的原始分数和排名；
- 同时被两路命中的文档累加两路 RRF 贡献；
- 只被一路命中的文档仍可进入结果；
- RRF 同分时依次按最佳输入排名和 `document_id` 稳定排序；
- 单路结果中出现重复 ID 时快速失败；
- 相同 ID 对应不同标题或正文时快速失败，避免 Citation 证据不一致。

## 6. Hybrid Retrieval Service

`HybridRetrievalService` 通过依赖注入组合：

```text
VectorRetriever
BM25Retriever
FusionStrategy
```

Hybrid 执行路径：

```text
Query
├── Vector Top 10
└── BM25 Top 10
        ↓
      RRF
        ↓
   Final Top K
```

Vector 与 BM25 并发执行。组件异常会继续向上抛出，不会被转换成虚假的正常空结果。正常无结果则返回：

```text
low_confidence = true
confidence_reasons = ["no_retrieval_results"]
```

诊断信息包括两路候选数、融合候选数、最终返回数以及各阶段耗时。

## 7. 验证结果

最终专项验证：

```text
Retrieval：81 passed, 1 skipped
```

专项测试显式启用了 PostgreSQL 集成，覆盖：

- 真实知识库语料加载；
- 使用真实语料构建和搜索 BM25；
- 真实 pgvector 查询；
- 不产生费用的 Mock Query Embedding。

唯一跳过项为需要真实 Qwen Embedding 费用授权的测试。

完整回归：

```text
后端：260 passed, 3 skipped
前端：11 test files passed, 81 tests passed
```

完整后端默认跳过三个显式集成测试；这些测试已在专项流程中执行两个，剩余一个是付费真实供应商测试。

静态和运行门禁：

- Secret 扫描通过；
- 架构边界通过；
- 1536 维 Embedding 契约通过；
- `git diff --check` 通过；
- API 与 Web 镜像重新构建成功；
- API、Web、PostgreSQL、Redis 四个服务健康；
- API `/health` 返回 HTTP 200；
- Web 首页返回 HTTP 200。

统一 Harness 最后的 `verify-compose.ps1` 仍受仓库既有中文编码解析错误影响。已手动执行该脚本的等价完整构建、健康检查和 HTTP 冒烟流程。

前端安装仍报告 14 个已有依赖漏洞，其中 2 个低危、11 个高危、1 个严重。本阶段没有修改前端依赖，也没有执行破坏性的 `npm audit fix --force`。

## 8. 已知限制

- BM25 索引只保存在单个应用进程内；
- 应用启动组合根尚未接入 BM25 自动构建；
- 知识库变化后需要调用方执行完整 `rebuild()`；
- 多进程实例各自维护索引，暂不自动同步；
- 当前未增加 BM25 索引缓存或版本号；
- RRF `k=60` 尚未经过正式 Eval；
- `HybridRetrievalService` 尚未注入生产 Agent；
- `hybrid_rerank` 尚不可用；
- 尚未计算 Recall@3、MRR 或三策略对比结果。

## 9. 回滚说明

本阶段没有数据库迁移，没有修改知识库数据，也没有切换生产检索入口。

回滚时可移除新增 Tokenizer、BM25、Fusion 和 Hybrid Service，并从 `pyproject.toml`、`uv.lock` 删除新增依赖。旧 `search_knowledge_base` 仍可继续运行。

## 10. 下一阶段建议

阶段五实现可替换 Reranker：

1. 增加 `NoOpReranker` 和首个真实实现；
2. 限制候选数量与单篇正文长度；
3. 校验 Reranker 只能返回候选集合中的 ID；
4. 处理未知 ID、重复 ID、字段缺失、超时和供应商异常；
5. 失败时回退到 RRF 顺序，并写入诊断原因；
6. 让 `hybrid_rerank` 返回最终 Top 3；
7. 保留 `vector_only` 和 `hybrid` 作为评测基线。
