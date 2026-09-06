# 开发者 B 阶段五报告：Agent Evaluation

## 1. 执行结论

阶段五已经完成。仓库新增了 30 条版本化 Agent 数据集、离线 LangGraph 执行器、显式授权的 Live 执行入口和自动计算的质量/路由/延迟指标。

默认命令不会访问数据库或模型供应商：

```bash
python -m evals.agent_eval
```

报告写入已由 `.gitignore` 排除的 `evals/reports/agent-latest.json`。只有增加 `--execute-live` 才会连接 PostgreSQL、Hybrid Retrieval 和 Qwen。

## 2. 新增产物

```text
evals/agent_dataset.py
evals/agent_eval.py
evals/datasets/agent_v1.jsonl
tests/test_evals/test_agent_dataset.py
tests/test_evals/test_agent_eval.py
```

## 3. 数据集构成

Agent v1 共 30 条，按 20 条 tuning、10 条 validation 固定划分，覆盖：

- 12 条中英文/混合语言正常可回答问题；
- 6 条退款、法律、删除账户高风险问题；
- 4 条知识库无答案问题；
- 2 条低置信度问题；
- 4 条未知、重复或缺失 Citation marker 的故障注入；
- 1 条 Rewrite 失败回退；
- 1 条 Reranker 降级；
- 2 条 Generation Provider 失败。

每条记录都包含 ID、Query、预期状态、是否应升级、预期文档标题、标签、场景和数据划分。Loader 会拒绝重复 ID、非法状态/场景、非布尔升级标签、矛盾的状态标签和非法 split。

## 4. 执行方式

### 4.1 Offline

Offline 模式逐条构建并运行真实 LangGraph 拓扑，通过场景化 Fake 注入：

- 检索文档、低置信度和无结果；
- Rewrite 异常；
- Reranker fallback 诊断；
- 正常、越界、重复和缺 marker 的生成结果；
- Generation Provider 异常。

因此指标来自 Graph 的实际状态和路由，不是按标签手工填写。Fake 只替代外部 PostgreSQL、Embedding、Reranker 和 Chat Provider。

### 4.2 Live

```bash
python -m evals.agent_eval --execute-live \
  --output evals/reports/agent-live.json
```

Live 模式需要真实环境变量，并会产生模型费用。它跳过只能由 Offline Fake 精确注入的 Citation/Provider/Rewrite/Reranker 故障案例，只评估可由真实系统观察的正常、无答案和低置信度案例。

本阶段没有执行 Live 模式，因为用户没有授权供应商费用，且当前验收重点是建立可重复评测基线。

## 5. Offline 评测结果

本机一次完整运行结果：

| 指标 | 结果 |
|---|---:|
| Evaluated Cases | 30 |
| Expected Status Accuracy | 100% |
| Correct Escalation Rate | 100% |
| High-risk Miss Rate | 0% |
| False Escalation Rate | 0% |
| Grounded Answer Rate | 83.33% |
| Citation Validity Rate | 83.33% |
| P50 Latency | 2.70 ms |
| P95 Latency | 4.73 ms |
| Unexpected Failed Cases | 0 |

Grounded Answer Rate 和 Citation Validity Rate 的分母是 24 条实际取得证据并进入生成的案例。其中 4 条是故意注入的 Citation 故障，均被 Graph 判定为不 grounded 并进入人工审核，因此结果为 20/24（83.33%）。这里的 83.33% 表示输入生成结果中有 4 条故障，并不表示安全路由失败；这 4 条的拦截率为 100%。

无答案案例和预期 Provider 失败不进入 Citation 指标分母。

Offline 延迟只反映 Python、LangGraph 和 Fake 节点开销，不能代表 PostgreSQL、Embedding、Reranker 和 Qwen 的生产 P95。

## 6. 自动化测试

新增测试验证：

- 数据集数量、划分和场景覆盖；
- 非法场景和非布尔升级标签被拒绝；
- 30 条 Offline Eval 不需要 API Key；
- 状态准确率、升级正确率和高风险漏判；
- Rewrite fallback 和 Reranker fallback 场景实际执行；
- 空结果不能生成汇总指标。

阶段完成后的后端结果：

```text
Backend full suite: 324 passed, 4 skipped
Python compileall: passed
```

## 7. 已知限制

- Offline 指标验证的是控制流、安全边界和指标实现，不代表真实 Qwen 回答质量；
- Live 模式会访问真实知识库和供应商，尚未在本阶段运行；
- 数据集规模仍小，且部分问题复用 Retrieval v1 的知识主题；
- 当前没有 LLM-as-judge，Grounding 仍使用确定性 Citation 契约；
- P50/P95 没有并发负载含义；
- Eval 直接运行 Graph，不写 CRM 客户、工单和消息，业务持久化由 Application/API 测试验证。

## 8. 回滚方法

- 删除 `evals/agent_dataset.py`、`evals/agent_eval.py` 和 Agent v1 数据集；
- 删除对应 Eval 测试；
- 不影响 API、Graph、数据库和现有 Retrieval Eval；
- `evals/reports/` 仅含忽略的本地产物，可以安全重新生成。

## 9. 下一阶段

阶段六将完成：

- README 与真实主链路同步；
- API/前端契约和两条核心 Demo 的自动化验收；
- 前后端全量测试、生产构建与 Harness 等价门禁；
- Compose 配置/构建和健康检查的可执行性核对；
- 最终集成报告、未执行项、剩余风险和后续建议。
