# 长文档切片对照评测指南

## 1. 本次交付与边界

新增独立评测语料、来源/证据标签和可执行的对照评测入口，不是正式知识库迁移。原有 18 篇种子文章、30 条 v1、300 条 v2 评测集均保留。服务端检索、API、前端引用结构、缓存版本和默认阈值不变。

语料清单：`evals/corpus/long_v1/manifest.json`；配套问题：`evals/datasets/retrieval_long_v1.jsonl`；新入口：`python -m evals.long_document_eval`。旧的 `evals.retrieval_eval` 仍服务于标题标签的 v1/v2，不要把新 JSONL 直接传给旧入口。

长文档基于种子文件中的虚构产品资料，扩展操作说明、相近概念区别和示例，不是复制段落凑长度。产品规则沿用种子资料；安全操作建议不是新产品功能。价格、认证和合规描述均属于虚构测试资料，不是对真实产品的核实或背书。新资料不得直接当作客户可见产品文档发布。

这是需要人工复核的合成基准，不代表生产流量，也不足以单独证明上线收益。

## 2. 语料组织

| 稳定来源 ID | 内容 | 原文章数 | 查询分区 |
| --- | --- | ---: | --- |
| account-access | 密码重置、登录排障、双因素认证 | 3 | tuning |
| workspace | 入门、项目、任务看板 | 3 | tuning |
| billing | 套餐、发票 | 2 | validation |
| developer | API、Webhook、集成 | 3 | validation |
| data-lifecycle | 团队权限、导出、账号删除 | 3 | test |
| operations | 偏好、通知、性能、安全 | 4 | test |

每篇约 4200～4500 个字符，保留英文来源语言，配套包含中文查询。默认 1200 字符上限、150 字符重叠得到 34 个片段；整篇方案为同样的 6 篇完整文章。参数以程序预览输出为准，字符不是 token。

36 个问题包含 30 个有答案、6 个无答案，其中 6 个有答案问题需要两个来源共同支持。每个分区有 12 个问题：10 个有答案、2 个无答案。问题覆盖文章前部、中后部、多段证据、跨来源和容易误答的缺失细节。

同一来源的标注问题只进入一个分区；`group_id` 标识意图组，禁止跨分区复用。跨来源问题的所有来源必须属于同一分区。全部来源始终同时进入检索语料，分开的是查询标签，不是把测试文档从知识库移除。

这种拆分减少同义问题泄漏，但不意味着事实完全不重合，也不代表已完成独立人工审查。每个分区只有两个无答案问题，误答率会以 50% 为步长变化，不能据此做稳健的生产阈值选择。正式校准前应增加独立问题、更多来源及无答案样本；不能根据测试集失败案例反复调参后仍称该测试集为未见数据。

## 3. 标签映射

一个问题的标签示意如下：

```json
{
  "id": "example-case",
  "query": "How long is an export available?",
  "split": "test",
  "group_id": "export-availability",
  "tags": ["late-evidence"],
  "evidence": [
    {
      "source_id": "data-lifecycle",
      "quote": "Exports are available for download for 7 days."
    }
  ]
}
```

quote 必须在指定原文中精确且唯一出现。加载器将其解析为字符范围 `[start, end)`，再通过与实际入库完全相同的 `prepare_source` 生成稳定切片 UUID、来源和范围。所有问题和答案标注都在语料之外，不会被入库。

没有答案使用 `evidence: []` 和 `no-answer` 标签。加载器检查重复问题、ID、证据，未知来源、缺失原句和分区泄漏。找不到原句直接报错，不会把坏标签当作无答案。

来源清单、正文和问题共同生成 `corpus_fingerprint`。同一材料的整篇和切片方案指纹一致，材料变化会改变指纹。对比时还要核对变体、切片参数、模型、K 和阈值。

## 4. 指标口径

### 来源级 Recall@K 与 MRR

来源级 Recall@K = 前 K 个结果覆盖的相关来源数 / 标注相关来源总数。

K 表示原始返回位置，不是去重后再补足 K 个来源。同一来源多片只计一次召回，但仍占据多个位置。MRR 使用第一个相关来源的原始排名倒数，再对有答案问题平均；第 K 位之后才命中按 0 计。

例如返回 A1、A2、B1，问题只与 B 相关，RR 是 1/3，不能先把 A1、A2 合并后算成 1/2。

### 证据级 Recall@K 与 MRR

证据级 Recall@K = 前 K 个结果完整覆盖的标注证据数 / 该问题标注证据总数。

来源相同还不够，片段必须完整包含证据范围。同一证据出现在两个重叠片段里，也只计一次。证据级 MRR 看第一次命中任意证据的位置，因此不能说明多步问题是否找全。`all_evidence_covered_at_k` 补充衡量全部证据是否找齐；只找到两个必需来源之一时，这项为 0，即使 MRR 为 1。

当前采用保守的完整包含规则：原句被切断时，两个片段各拿一半不会自动算作完整命中。预览的 `uncoverable_evidence` 列出整个片段库都无法单片覆盖的证据，这些仍是有答案标签，按缺失计算。它可能低估生成器拼接片段后的能力，因此另需生成端评测，不能把它当作 Answer Correctness。

### 片段级 Recall@K

`chunk_recall_at_k` 的相关集合是整个变体中至少完整包含一条标注证据的所有片段。它用于观察片段召回，但切片参数会改变分母，不能直接拿不同变体的这项证明收益。

主要跨方案比较采用稳定来源和稳定证据口径。相同 K 下整篇带入的文本通常更多，这是固定返回数量、不是固定 token 预算实验。生成效果还应补做相同上下文预算的对照。

### 拒答、延迟、降级

真实评测的 `raw_metrics` 不经过低置信度过滤；`accepted_metrics` 将拒绝的问题视为空结果。

无答案识别以“应该拒绝”为正类：Precision 看拒绝中多少确实无答案，Recall 看无答案中多少被拒绝。误答率 `false_accept_rate` 是无答案请求被接受的比例，误拒率是有答案请求被拒绝的比例。这里的误答率是错误放行代理指标，不是最终自然语言答案正确性。

未发生拒绝时 Precision 为 null，不是假定为 0 或 1。离线 BM25 没有运行时置信度策略，拒答指标和 accepted_metrics 均为 null，不能用 BM25 分数校准向量阈值。

P95 包围单次检索，排除启动、入库、标签加载和 BM25 建索引；并发固定为 1。离线 BM25 延迟不是端到端 Agent 延迟。在线降级率来自真实 fallback 标记。向量供应商失败单独计为 operational failure，不算正确拒答，报告保留失败 ID；存在失败时应先补测再比较完整结果。

## 5. 先执行完全离线验证

在仓库根目录执行：

```powershell
python -m evals.long_document_eval --action preview --variant whole
python -m evals.long_document_eval --action preview --variant chunked
python -m evals.long_document_eval --action bm25 --variant whole
python -m evals.long_document_eval --action bm25 --variant chunked
```

需要本地报告可加 `--output evals/reports/long-v1-bm25-chunked.json`。该目录已被忽略，报告不应提交。离线命令不加载 `.env`，不连库、不创建模型客户端。

英文语料和中文查询的纯词面匹配存在限制。BM25 离线对照用于验证流程和建立词面基线，不等于 `hybrid_rerank` 的效果。

## 6. 隔离库中的完整链路实验

准备两个空白 PostgreSQL + pgvector 数据库，分别用于 whole 和 chunked。不要将两种变体混在一个库，也不要删除正式库的旧文章换新文章。

为当前变体显式设置服务端 `LONG_DOCUMENT_EVAL_DATABASE_URL`，以及模型所需 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`。不要把值写入文档、前端或 Git。新入口不回退使用应用的 `DATABASE_URL`。

先确认连接目标是新建隔离库。迁移脚本仍读取 `DATABASE_URL`，因此仅在当前终端执行迁移时临时切换并恢复：

```powershell
if (-not $env:LONG_DOCUMENT_EVAL_DATABASE_URL) {
    throw '请先设置指向空白隔离评测库的 LONG_DOCUMENT_EVAL_DATABASE_URL'
}
$previousAppDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = $env:LONG_DOCUMENT_EVAL_DATABASE_URL
    python -m database.migrations.run_migration --migration 001_initial_schema.sql
    if ($LASTEXITCODE -ne 0) { throw '迁移 001 失败' }
    python -m database.migrations.run_migration --migration 003_knowledge_chunk_provenance.sql
    if ($LASTEXITCODE -ne 0) { throw '迁移 003 失败' }
} finally {
    $env:DATABASE_URL = $previousAppDatabaseUrl
}
```

程序不会替你创建或清空数据库。以下为后续真实执行命令：`--execute-live` 会授权模型调用，import 还会写入所指定的隔离库。本次开发验证没有执行真实供应商步骤。

```powershell
# 当前连接指向 whole 专用库。
python -m evals.long_document_eval --action import --variant whole --execute-live
python -m evals.long_document_eval --action evaluate --variant whole --strategy hybrid_rerank --threshold 0.43 --execute-live --output evals/reports/long-v1-whole-live.json

# 切换 LONG_DOCUMENT_EVAL_DATABASE_URL 到已迁移的 chunked 专用库后执行。
python -m evals.long_document_eval --action import --variant chunked --execute-live
python -m evals.long_document_eval --action evaluate --variant chunked --strategy hybrid_rerank --threshold 0.43 --execute-live --output evals/reports/long-v1-chunked-live.json
```

import 拒绝含无关文档或其他切片参数的库；每篇来源在一个事务写入，整个语料不是一个跨模型调用的大事务。中途失败可能已有完整来源写入，可以恢复执行。重复导入不会重复写入，但当前仍会重新请求 Embedding，注意费用。

evaluate 在付费查询前验证所有 UUID、正文、标题、分类和来源配置与清单一致，避免误测旧库。Embedding 仍为 `text-embedding-v4`、1536 维，不能混用向量空间。在线评测不走 Redis，每次重建隔离库的 BM25 快照，不影响应用进程索引。

whole 使用相同入库函数，字符上限 100000、重叠 0，保持完整文章；chunked 默认 1200/150。两组标题使用相同生成规则，Embedding 输入同样为原始来源标题加正文。

Reranker 沿用现有候选数量和每篇 2000 字符截断。整篇中后部事实可能不进入 Reranker 输入，切片则可能进入。这是当前流水线的真实差异，不表示隔离了纯 Embedding 切片效应。可用 `--strategy vector_only`、`--strategy hybrid` 补充阶段对照。

## 7. 阈值和上线条件

代码默认低置信度阈值仍为 0.40。示例显式传入 0.43 只是检验之前的候选值，不修改运行时默认值，也不表示适合长文档。

本次未更换模型、激活长文档或校准阈值，未产生真实 hybrid_rerank、Answer Correctness、Faithfulness 或人工转接效果报告。离线回归不能替代它们。

后续先人工复核语料和无答案标签、扩大独立评测集；固定基线配置，执行两个变体的真实检索；只用调参/验证分区选择参数；冻结后对测试集验证；再补做生成与人工转接、上下文预算和延迟成本对比。未确认收益前保持现有库不变。

## 8. 开发验证

```powershell
python -m pytest tests/test_evals -q
powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1
```

测试涵盖标签解析、重复片段不抬高证据覆盖、原始排名保留、跨片证据缺失、分区泄漏、离线不连库、显式费用开关、错误数据库在模型客户端创建前被拒绝，以及低置信度与供应商失败分别统计。

若 Windows PowerShell 5 在现有 Compose 脚本出现中文解析错误，可用 PowerShell 7 单独执行 `scripts/harness/verify-compose.ps1`；必须记录总入口失败，不能说整个入口已通过。
