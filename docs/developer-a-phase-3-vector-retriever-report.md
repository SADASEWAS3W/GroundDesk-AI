# 开发者 A 阶段三报告：独立 Vector Retriever

## 1. 执行结论

阶段三的代码实现已经完成。项目新增独立的 `PgVectorRetriever`，通过注入的模型客户端和 PostgreSQL 连接池执行 Qwen Embedding 与 pgvector 余弦检索，并将结果映射到阶段二冻结的 `RetrievedDocument` 契约。

现有生产 `search_knowledge_base` Function Tool 没有修改，生产 Agent 也尚未切换到新 Retriever，因此本阶段可以通过删除新增文件和导出安全回退。

PostgreSQL/pgvector 集成测试已经在 Docker Compose 数据库中通过，测试使用已有文档向量作为 Mock Query Embedding，不产生模型费用。真实供应商集成测试未执行，因为本轮没有真实模型费用调用授权。

## 2. 当前与目标检索配置

| 项目 | 当前生产 Tool | 新 PgVectorRetriever |
|---|---|---|
| Embedding 模型 | `text-embedding-v4` | `text-embedding-v4` |
| 维度 | 1536 | 1536，构造和响应时双重校验 |
| 距离 | pgvector cosine `<=>` | pgvector cosine `<=>` |
| 分数方向 | `1 - distance`，越大越相关 | `1 - distance`，越大越相关 |
| IVFFlat probes | 10 | 10，可注入配置 |
| 默认 Top K | 3 | 10 |
| 默认阈值 | 0.25 | 无阈值 |
| 查询参数 | 向量字符串内联 | `$1::vector` 参数绑定 |

新 Retriever 默认不沿用生产 Tool 的 `0.25` 阈值。阶段一已经证明该阈值会放行知识库外问题，RAG 规则也要求阈值必须由 Eval 校准。为了复现旧基线，新 Retriever 支持显式传入 `similarity_threshold=0.25`。

本阶段没有更换 Embedding 模型或维度，现有数据库向量与查询向量兼容，不需要知识库重建或缓存迁移。

## 3. 新增和修改文件

新增：

```text
agent/retrieval/vector.py
tests/test_retrieval/test_vector.py
tests/test_retrieval/test_vector_integration.py
tests/test_retrieval/test_vector_pg_integration.py
docs/developer-a-phase-3-vector-retriever-report.md
```

修改：

```text
agent/retrieval/__init__.py
```

未修改：

```text
agent/tools/knowledge.py
agent/customer_success_agent.py
api/main.py
database/migrations/
web/
```

## 4. 实现行为

`PgVectorRetriever.search()` 当前行为：

- 标准化首尾空白和重复空白；
- 空 Query 返回空列表，不调用模型或数据库；
- 显式请求 `text-embedding-v4`、1536 维和 float 编码；
- 拒绝错误维度、`NaN` 和正负无穷向量；
- 使用 PostgreSQL 参数绑定传递查询向量；
- 在事务内设置 `ivfflat.probes`；
- 按余弦距离升序返回候选；
- 输出稳定字符串 `document_id`；
- 输出 `vector_score`、从 1 开始的 `vector_rank` 和原始距离；
- Embedding 供应商失败和数据库失败抛出 `VectorRetrievalError`，不会伪装成正常空结果。

返回文档的来源字段为：

```python
source_retrievers=("vector",)
metadata={
    "source": "knowledge_base",
    "vector_distance": distance,
}
```

## 5. 测试覆盖

新增的 16 个单元测试覆盖：

- 正常召回和字段映射；
- Query 标准化；
- 1536 维 Embedding 请求；
- 向量参数化 SQL；
- Top 10 和自定义 Top K；
- 显式基线阈值；
- 空 Query；
- 非法 Top K；
- 错误 Embedding 维度；
- 非有限 Embedding 值；
- 供应商异常；
- 数据库异常；
- 非法构造配置。

本次专项结果：

```text
16 passed
```

完整验证结果：

```text
后端：233 passed, 1 skipped
前端：11 test files passed, 81 tests passed
PostgreSQL/pgvector 集成：1 passed
Compose：4 个服务健康
HTTP：API 200，Web 200
```

后端跳过的 1 项是需要显式授权真实供应商调用的集成测试。

PostgreSQL/pgvector 集成测试使用数据库中已有文档向量作为 Mock Query Embedding，不产生模型费用。显式设置以下配置后运行：

```text
RUN_PGVECTOR_INTEGRATION=1
DATABASE_URL
```

真实供应商集成测试默认跳过。只有显式设置以下开关并提供服务端配置时才会产生真实供应商调用：

```text
RUN_RETRIEVAL_INTEGRATION=1
DATABASE_URL
DASHSCOPE_API_KEY
DASHSCOPE_BASE_URL
```

## 6. 尚未完成的验证

以下验证仍需要 Eval 数据或真实模型调用授权后补做：

- 与阶段一八条 Vector-only 查询逐条对比；
- Recall@3、MRR 和正式失败案例报告。

Recall@3、MRR 和阈值校准属于阶段六、阶段七；在 Eval 数据准备完成前不会为新 Retriever 固化默认相关性阈值。

## 7. 已知限制

- 新 Retriever 尚未被 `RetrievalService` 的真实组合实现调用；
- 生产 Agent 仍走旧 Function Tool；
- 当前只实现 Vector 候选召回，不包含缓存、BM25、RRF 或 Reranker；
- 单次查询会调用一次外部 Embedding 服务；
- 原始距离暂存于文档 metadata，未新增公共顶层字段；
- 组件异常需要由后续统一 Retrieval Service 转换为路由所需的结构化失败状态。

## 8. 下一阶段建议

进入阶段四前，应先补做真实 pgvector 集成验证。随后实现：

1. 中英文统一 Tokenizer；
2. 内存 BM25 索引和重建接口；
3. 以稳定 `document_id` 去重的 RRF；
4. 组合 Vector Top 10 和 BM25 Top 10 的真实 Retrieval Service；
5. 保持本阶段 `PgVectorRetriever` 的接口不变。
