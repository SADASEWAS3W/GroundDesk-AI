# 开发者 A 阶段五报告：可替换 Reranker 与安全降级

## 1. 执行结论

阶段五代码实现已经完成。项目新增 `NoOpReranker`、基于注入式 OpenAI-compatible Chat Client 的 `LLMReranker`，并在 `HybridRetrievalService` 中正式启用 `hybrid_rerank` 策略。

当前三种检索策略均具有明确行为：

```text
vector_only
hybrid
hybrid_rerank
```

Reranker 超时、供应商异常、格式错误或候选集合违规时，完整请求不会失败，而是回退到 RRF 顺序。降级状态和原因会写入 `RetrievalDiagnostics`。

本阶段没有切换生产 Agent。旧 `search_knowledge_base` Function Tool 仍是生产入口。

## 2. 新增和修改内容

新增：

```text
agent/retrieval/reranker.py
tests/test_retrieval/test_reranker.py
tests/test_retrieval/test_reranker_integration.py
docs/developer-a-phase-5-reranker-report.md
```

修改：

```text
agent/retrieval/__init__.py
agent/retrieval/service.py
tests/test_retrieval/test_hybrid_service.py
```

本阶段没有增加第三方依赖，没有修改数据库、Embedding 模型、向量维度或缓存版本。

## 3. Reranker 接口实现

两个实现都遵守阶段二定义的 `Reranker` Protocol：

```python
async def rerank(
    query: str,
    documents: Sequence[RetrievedDocument],
    *,
    top_k: int,
) -> list[RetrievedDocument]:
    ...
```

### 3.1 NoOpReranker

`NoOpReranker` 用于确定性测试、联调和关闭真实模型重排的场景：

- 保留 RRF 候选顺序；
- 按 Top K 截断；
- 重新填写从 1 开始的 `final_rank`；
- 返回文档副本；
- 不产生外部模型调用。

### 3.2 LLMReranker

`LLMReranker` 使用注入的模型客户端执行结构化相关性评分。默认模型名为：

```text
qwen-plus
```

该实现属于基础版允许的“LLM 结构化打分”方案，不创建模型客户端，也不读取 API Key。

默认输入限制：

```text
最大候选数：20
单篇正文：2000 字符
Query：1000 字符
```

服务当前默认只向 Reranker 传入 RRF Top 10，因此正常路径低于最大候选限制。

## 4. 模型输出契约

模型必须返回：

```json
{
  "rankings": [
    {
      "document_id": "candidate-id",
      "score": 0.9
    }
  ]
}
```

校验规则：

- 每个候选 ID 必须且只能出现一次；
- 不允许引入候选集合之外的 ID；
- 每项必须包含 `document_id` 和数值 `score`；
- Score 必须为 0 到 1 之间的有限数；
- 必须覆盖全部候选，不能只返回 Top K；
- Score 越大表示越相关；
- 同分时保持原 RRF 顺序，再以文档 ID 稳定排序。

未知和重复 ID 会先被丢弃；如果丢弃后无法完整覆盖候选集合，则整个模型结果判定为无效，由 Service 回退到 RRF。这保证 Reranker 无法扩展 Citation 来源集合。

## 5. Service 接入与降级

`HybridRetrievalService` 新增：

```text
reranker
reranker_timeout_seconds
```

默认超时：

```text
10 秒
```

`hybrid_rerank` 路径：

```text
Vector Top 10 ──┐
                ├── RRF ── LLM Reranker ── Final Top 3
BM25 Top 10 ────┘
```

降级原因使用稳定代码：

| 场景 | fallback_reason |
|---|---|
| 超时 | `reranker_timeout` |
| 模型供应商失败 | `reranker_provider_error` |
| 未知 ID、重复 ID、缺字段、错误数量或错误分数 | `reranker_invalid_output` |
| 其他未分类异常 | `reranker_error` |

发生降级时：

- `reranker_fallback=True`；
- 最终结果按 RRF 顺序返回；
- `rerank_score` 保持为空，避免把 RRF 分数伪装成模型评分；
- `final_rank` 重新从 1 开始；
- 请求不会因为 Reranker 故障而整体失败。

如果构造 Service 时完全没有配置 Reranker，却请求 `hybrid_rerank`，会抛出 `RetrievalCapabilityError`。配置缺失属于部署错误，不伪装成运行时降级。

## 6. 测试覆盖

本阶段新增测试覆盖：

- NoOp 顺序与 Top K；
- 正常模型结构化打分和排序；
- 同分稳定排序；
- Query 与正文截断；
- 最大候选限制；
- 未知文档 ID；
- 重复文档 ID；
- 缺失 Score；
- `NaN`、Infinity 和越界 Score；
- 非 JSON 输出；
- 供应商异常；
- Service 对返回数量、候选子集和 `rerank_score` 的二次校验；
- Provider 异常降级；
- 非预期异常降级；
- 非法输出降级；
- 超时降级；
- 非法超时配置。

真实 Reranker 集成测试已提供，但默认关闭。只有显式设置以下开关才会产生模型费用：

```text
RUN_RERANKER_INTEGRATION=1
DASHSCOPE_API_KEY
DASHSCOPE_BASE_URL
QWEN_RERANK_MODEL（可选）
```

本轮未获得真实模型费用调用授权，因此没有执行该测试。

## 7. 验证结果

完整回归：

```text
后端：285 passed, 4 skipped
前端：11 test files passed, 81 tests passed
```

四个跳过项为显式集成测试：

- 两个 PostgreSQL/pgvector 与 BM25 集成测试；
- 一个真实 Query Embedding 测试；
- 一个真实 LLM Reranker 测试。

其中两个无费用 PostgreSQL 测试已单独显式执行：

```text
2 passed
```

静态和运行门禁：

- Secret 扫描通过；
- 架构边界通过；
- 1536 维 Embedding 契约通过；
- Python 编译检查通过；
- `git diff --check` 通过；
- API 和 Web 镜像重新构建成功；
- API、Web、PostgreSQL、Redis 全部健康；
- API `/health` 返回 HTTP 200；
- Web 首页返回 HTTP 200。

统一 Harness 最后仍受 `verify-compose.ps1` 的既有中文编码解析错误影响；本次已手动执行其等价完整检查。

前端仍报告 14 个已有依赖漏洞，其中 2 个低危、11 个高危、1 个严重。本阶段未修改前端依赖。

## 8. 验收标准对应

| 阶段五验收标准 | 结果 |
|---|---|
| `hybrid_rerank` 返回最终 Top 3 | 通过 |
| Reranker 故障不导致完整请求失败 | 通过 |
| 降级信息写入 diagnostics | 通过 |
| 测试使用 Fake/Mock，不产生 API 成本 | 通过 |
| Reranker 不能引入候选集合外 Citation 来源 | 通过 |
| 正常、同分、未知 ID、重复 ID、缺字段、超时和异常均有测试 | 通过 |

## 9. 已知限制

- `LLMReranker` 使用通用 Chat Model 结构化评分，不是专用 Cross-Encoder；
- 尚未通过真实供应商调用验证 `response_format=json_object` 的兼容性；
- Reranker 模型名、超时和输入长度尚未接入统一环境配置；
- Hybrid Service 尚未注入生产 Agent；
- Reranker 降级暂不直接标记 `low_confidence`，后续由 Eval 与 HITL 路由共同决定；
- 尚未计算 Recall@3、MRR 或 Reranker 改善幅度；
- 当前没有重排请求缓存。

## 10. 回滚说明

本阶段没有数据库迁移、知识库修改或生产入口切换。

回滚时可移除 `reranker.py`、对应测试和 Service 的可选 Reranker 分支。`vector_only`、`hybrid` 和旧生产 Tool 均可继续工作。

## 11. 下一阶段建议

阶段六建立 Retrieval Eval：

1. 准备约 30 条带稳定 `relevant_document_ids` 的 JSONL 数据；
2. 实现 Recall@3 和 MRR；
3. 在相同数据上运行 `vector_only`、`hybrid`、`hybrid_rerank`；
4. 输出每种策略的指标、P50/P95 延迟和降级次数；
5. 记录失败 Query 及各阶段排名；
6. 使用评测结果决定 RRF 参数、候选数量与后续置信度信号。
