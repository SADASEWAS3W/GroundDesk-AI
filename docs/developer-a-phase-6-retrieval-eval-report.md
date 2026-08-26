# 开发者 A 阶段六报告：Retrieval Eval 框架

## 1. 执行结论

阶段六的评测框架、30 条数据集、指标和三策略真实运行器已经完成。离线数据与指标测试通过。

本轮没有执行三策略真实模型评测，因为 `vector_only`、`hybrid` 和 `hybrid_rerank` 会产生真实 Query Embedding 与 Reranker 调用，而当前没有本轮费用授权。运行器要求显式传入 `--execute-live`，避免误产生费用。

因此当前状态是：评测工程能力完成，真实 Recall@3、MRR 和策略对比数字待授权执行后生成。

## 2. 数据集

`evals/datasets/retrieval_v1.jsonl` 共 30 条，覆盖：

- 中英文和中英混合；
- 同义表达与精确关键词；
- Password、2FA、API、Webhook、Billing、Export 等知识主题；
- 多文档相关问题；
- 退款、量子计算和法律咨询等知识库无答案问题。

其中 27 条为可回答问题，3 条为无答案问题。

当前 Seed 每次插入会生成随机 UUID，无法把数据库 UUID 直接固化进可复现数据集。数据集暂以唯一文章标题作为稳定标签，真实运行时先校验标题唯一性，再解析为当前数据库 UUID；指标最终仍使用 UUID 计算。

这是兼容方案，不等于数据库已经具备稳定业务 ID。后续应单独修复 Seed 幂等性和稳定 ID。

## 3. 指标

已实现：

- Recall@K，默认报告 Recall@3；
- MRR；
- 无答案准确率；
- P50/P95 端到端检索延迟；
- Reranker 降级次数；
- 失败 Query 明细。

无答案样本不参与 Recall 和 MRR，单独计算“预测结果为空”的准确率，避免将无相关文档集合错误代入 Recall。

## 4. 三策略运行器

运行器使用同一数据集依次执行：

```text
vector_only
hybrid
hybrid_rerank
```

真实运行命令：

```powershell
python -m evals.retrieval_eval --execute-live --output evals/reports/retrieval-v1.json
```

所需服务端配置：

```text
DATABASE_URL
DASHSCOPE_API_KEY
DASHSCOPE_BASE_URL
QWEN_RERANK_MODEL（可选）
```

未提供 `--execute-live` 时，命令会退出并说明需要显式授权，不会访问供应商。

生成报告目录已加入 `.gitignore`，避免提交生成报告和可能包含运行诊断的本地产物。

## 5. 失败明细

每个未命中样本记录：

- Eval ID；
- Query；
- 标准相关数据库 UUID；
- 实际预测 UUID；
- 实际预测标题；
- Tags。

这些字段足以在下一阶段结合 Vector、BM25、RRF 和 Reranker 排名继续分类失败原因。当前报告尚未包含每个中间阶段的完整排名快照，这是后续增强项。

## 6. 验证

离线指标与数据集测试：

```text
5 passed
```

完整后端回归：

```text
290 passed, 4 skipped
```

覆盖 Recall、MRR、无答案样本、P95、30 条数据加载和重复 Eval ID 拒绝。

静态门禁通过：

- Secret 扫描；
- 架构边界；
- 1536 维 Embedding 契约；
- Python 编译；
- `git diff --check`。

## 7. 尚未完成的验收项

以下项目必须在费用授权后执行，不能用手写数字代替：

- 三种策略的真实 Recall@3；
- 三种策略的真实 MRR；
- P50/P95 真实延迟；
- Reranker 实际降级次数；
- 真实失败案例及分类；
- Hybrid 与 Hybrid + Reranker 是否优于 Vector-only 的结论。

在真实报告生成前，阶段六不能宣称最终指标验收完成。

## 8. 已知限制

- 数据集规模较小，指标波动会较大；
- 标签尚未经过第二人复核；
- 数据库缺少稳定业务 ID，当前依赖唯一标题解析；
- 三策略顺序执行，未优化 Embedding 复用，真实运行会产生较多调用；
- 无默认相关性阈值，因此无答案 Vector Query 很可能仍返回候选；
- 报告尚未记录每个中间阶段的完整候选排名。

## 9. 下一步

1. 获得明确模型费用授权后运行一次 `retrieval_v1`；
2. 审阅 30 条标签并修正歧义；
3. 根据真实失败明细补充中间排名快照；
4. 进入阶段七进行参数和置信度校准；
5. 单独解决知识库稳定业务 ID 与 Seed 幂等性问题。
