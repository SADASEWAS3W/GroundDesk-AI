# Developer B：Retrieval v2 Live Eval 与阈值校准报告

日期：2026-09-06

状态：三策略 Live Eval 完成；共享默认值等待协作确认

## 1. 执行结论

Retrieval v2 的 300 条数据已完成 `vector_only`、`hybrid`、`hybrid_rerank` 三策略真实评测。三份报告均包含 300 条 case result，operational failure 均为 0。

- `vector_only` 是当前最快且最稳定的方案，Raw Recall@3 为 `0.9917`；
- `hybrid` 没有改善 v2，Raw Recall@3 下降到 `0.9771`；
- `hybrid_rerank` 的原始排序最好，Raw Recall@3 为 `1.0`、MRR 为 `0.9917`；
- 但 Qwen Reranker 有 71/300 次安全降级，P95 为 15.31 秒，使 accepted Recall@3 降到 `0.7708`；
- v2 tuning 证明 `0.425` 比当前 `0.40` 更适合作为 Vector 策略的候选阈值，但默认值会影响 HITL 路由，修改前需要协作确认。

## 2. 环境与数据契约

- Provider：阿里云百炼 OpenAI-compatible endpoint；
- Chat/Reranker：`qwen-plus`；
- Embedding：`text-embedding-v4`；
- Embedding 维度：1536；
- 知识库：18 篇文档、18 个有效向量；
- 数据集：300 条，其中 240 条可回答、60 条 no-answer；
- split：180 tuning、60 validation、60 test；
- 数据集使用的 18 个相关标题全部能映射到当前知识库。

查询与文档使用同一 Embedding 模型、维度和语义空间，满足当前 RAG 契约。

## 3. 三策略总体结果

### 3.1 Raw：只衡量检索与排序

| 策略 | Recall@3 | MRR | P50 | P95 | 检索失败案例 | Operational failure |
|---|---:|---:|---:|---:|---:|---:|
| Vector only | 0.9917 | 0.9667 | 182 ms | 304 ms | 0 | 0 |
| Hybrid | 0.9771 | 0.9653 | 176 ms | 270 ms | 3 | 0 |
| Hybrid + Reranker | 1.0000 | 0.9917 | 13.92 s | 15.31 s | 0 | 0 |

Raw 指标说明 Reranker 能改善排序，但当前 BM25 + RRF 本身没有超过 Vector。不能用 accepted 指标反推检索器的原始排序质量。

### 3.2 Accepted：应用 `0.40` 阈值和安全降级策略后

| 策略 | Recall@3 | MRR | No-answer accuracy | 低置信度 | 可回答误拒 |
|---|---:|---:|---:|---:|---:|
| Vector only | 0.9792 | 0.9563 | 0.9167 | 58 | 3 |
| Hybrid | 0.9604 | 0.9507 | 0.9167 | 61 | 6 |
| Hybrid + Reranker | 0.7708 | 0.7667 | 0.9667 | 113 | 55 |

Accepted 指标反映最终允许 Agent 使用的证据。它同时受阈值和 Reranker fallback 安全规则影响，不能与 Raw 指标当作同一条指标直接比较。

## 4. Reranker 风险拆分

`hybrid_rerank` 共发生 71 次降级，占 23.67%：

- `reranker_invalid_output`：40；
- `reranker_timeout`：31。

当前策略把所有 Reranker fallback 标记为低置信度并进入人工审核。在默认阈值 `0.40` 下：

- 阈值本身拒绝 57 条；
- fallback 安全规则拒绝 71 条；
- 两者重叠 15 条；
- 最终误拒 55 条可回答问题。

因此 Reranker accepted 指标下降的主因不是 `0.40` 阈值，而是通用 Chat 模型作为 Reranker 的超时和 JSON 稳定性。不能通过放松阈值掩盖 fallback。

## 5. 阈值校准

阈值只使用 tuning split 选择，validation 和 test 只用于冻结后验证。

### 5.1 Vector-only tuning 曲线

| 阈值 | Accepted Recall@3 | MRR | No-answer accuracy | 可回答误拒 | No-answer 拒绝 |
|---:|---:|---:|---:|---:|---:|
| 0.350 | 0.9792 | 0.9583 | 0.8056 | 1 | 29/36 |
| 0.400 | 0.9653 | 0.9479 | 0.8889 | 3 | 32/36 |
| **0.425** | **0.9653** | **0.9479** | **0.9444** | **3** | **34/36** |
| 0.450 | 0.9514 | 0.9375 | 0.9444 | 5 | 34/36 |
| 0.485 | 0.9514 | 0.9375 | 1.0000 | 5 | 36/36 |

`0.425` 相比 `0.40`：

- tuning 的 Recall@3、MRR 和可回答误拒数量不变；
- no-answer accuracy 从 `0.8889` 提升到 `0.9444`；
- `0.450` 开始额外误拒可回答问题，因此不选；
- 若追求 tuning no-answer 100%，需要约 `0.485`，但会牺牲更多可回答覆盖，不符合当前折中目标。

### 5.2 候选阈值 `0.425` 的冻结验证

Vector-only：

| Split | Recall@3 | MRR | No-answer accuracy | 可回答误拒 |
|---|---:|---:|---:|---:|
| Tuning | 0.9653 | 0.9479 | 0.9444 | 3/144 |
| Validation | 1.0000 | 0.9688 | 1.0000 | 0/48 |
| Test | 1.0000 | 0.9688 | 1.0000 | 0/48 |

总体上，`0.425` 与 `0.40` 的 accepted Recall@3、MRR 相同，no-answer accuracy 从 `0.9167` 提升到 `0.9667`。这是当前候选阈值的直接证据。

## 6. 策略建议

### 当前建议

1. 面试 Demo 和当前稳定链路优先使用 `vector_only`；
2. 默认 Vector 低置信度阈值候选从 `0.40` 调整为 `0.425`；
3. 保持“Reranker fallback 必须进入人工审核”的安全规则，不通过放松规则提高 accepted 指标；
4. `hybrid_rerank` 保留为实验策略，等待专用 Reranker、更严格输出解析或更低延迟模型后再评估；
5. 分析 Hybrid 的 3 个失败案例和 BM25/RRF 排名，确认是合成数据分布问题还是融合权重问题。

### Hybrid 失败簇

3 个 Raw Top-3 失败全部来自同一意图“初始设置通常需要多久”：

- `v2-010`：英文 direct 改写；
- `v2-011`：英文 support 改写；
- `v2-012`：中英混合改写。

预期文档是 Getting Started，实际 Top-3 被 Password Reset、2FA、Billing 等文档占据。Vector-only 对该簇仍能保留相关文档，而 BM25 + RRF 将其挤出 Top-3。这表明当前主要是一个词法融合失败簇；同时，样本中的 `How do I how long...`、`请问如何 how long...` 也具有明显合成痕迹，后续应同时检查 RRF 候选排名与数据表达自然度。

### 共享边界

阈值会改变 `low_confidence -> HITL` 路由，默认策略会改变 Graph 的检索行为。报告只给出候选建议；在协作确认前不修改 `RetrievalConfidencePolicy` 默认值或 Graph 默认策略。

## 7. 账户中断与恢复记录

首次把三策略放在一个进程中运行时，DashScope 在中途返回：

```text
HTTP 400
code: Arrearage
```

当时已主动停止，避免继续形成无效请求。充值恢复后先执行最小探针，再把三个策略拆开运行并分别保存，最终全部成功。

首次中断日志记录到 728 次 HTTP 200 和 152 次 HTTP 400，但由于旧 Runner 只在全部完成后写 JSON，这些请求不能作为指标样本。最终表格只使用充值后生成的三份完整报告。

## 8. 报告产物

以下查询级报告和日志位于被 Git 忽略的 `evals/reports/`，不提交到仓库：

- `retrieval-v2-vector.json`；
- `retrieval-v2-hybrid.json`；
- `retrieval-v2-rerank.json`；
- 对应的 `.log` 文件。

本文只保留聚合指标、决策依据和不包含凭据的运行事实。
