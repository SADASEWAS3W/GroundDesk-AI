# 开发者 B 阶段四报告：Query Rewrite 与 Grounded Generation

## 1. 执行结论

阶段四已经完成。生产 Graph 现在通过 Qwen OpenAI-compatible Chat API 执行单查询改写和结构化回答生成；自动化测试继续使用确定性实现和 Fake Client，因此不会产生模型费用。

生成链路只接收最终检索集合中的有界上下文，并要求模型同时返回回答与引用文档 ID。Graph 会对引用集合、回答中的 Citation marker 和最终检索文档做确定性闭合校验；没有证据、引用越界或引用不一致时不会自动交付，而是进入人工审核。

## 2. 新增模块

```text
agent/nodes/rewrite.py
agent/nodes/generate.py
```

### 2.1 Query Rewrite

`LLMQueryRewriter` 的约束：

- 每次只生成一个检索查询；
- 保留客户原始意图，不生成回答；
- 10 秒模型超时；
- 输出为空、调用失败或超时时，由 Graph 回退到标准化后的原问题；
- Graph 状态记录实际查询和是否发生回退。

### 2.2 Grounded Generation

`LLMAnswerGenerator` 的约束：

- 最多使用 Top 3 最终检索文档；
- 单篇输入最多 2000 字符；
- 模型输出最多 800 tokens；
- 只允许依据传入知识库上下文回答；
- 要求 JSON 返回 `answer` 和 `citation_document_ids`；
- 20 秒模型超时；
- 自动化测试使用 `ExtractiveAnswerGenerator`，不访问外部模型。

## 3. Grounding 与 Citation 校验

Graph 当前执行以下确定性检查：

1. 最终检索集合不能为空；
2. 生成器必须报告至少一个 Citation 文档 ID；
3. 报告的 ID 必须全部属于本次最终检索集合；
4. Citation ID 不得重复；
5. 构造出的 Citation 与生成器报告集合必须一致；
6. 回答中的 `[来源: document_id]` marker 必须存在；
7. marker 集合必须与 Citation 集合一致。

任一条件失败时，`grounding_passed=false`，回答转入 `waiting_review`，不会作为客户最终回答发送。

## 4. Graph 集成

生产组合边界现在注入：

```text
LLMQueryRewriter
LLMAnswerGenerator
HybridRetrievalService
```

Graph 的阶段顺序为：

```text
rewrite_query
→ retrieve
→ generate_answer
→ grounding_check
→ complete 或 human_review
```

高风险问题即使引用校验通过，也继续进入人工审核。低置信度或无证据问题不会绕过审核边界。

## 5. 测试

新增或扩展测试覆盖：

- Qwen Query Rewrite 正常返回、空输出和异常行为；
- Qwen Generator 结构化 JSON 解析和非法 JSON；
- Rewrite 异常时 Graph 回退原问题；
- Generator 返回未知文档 ID 时进入人工审核；
- 默认确定性生成器的引用闭合；
- Application Service 在 Graph 失败时执行失败补偿，不返回虚假成功；
- API、审核和旧 Runner 兼容路径回归。

验证结果：

```text
Phase 4 targeted suite: 50 passed
Backend full suite: 319 passed, 4 skipped
```

唯一警告来自 LangGraph Checkpoint Serializer 的未来默认值变更，不影响当前行为。

## 6. 费用与数据安全

- 单元和集成测试没有调用真实 Qwen；
- Prompt 只包含本次问题及有界知识片段；
- 模型密钥仍只存在服务端；
- 没有新增数据库字段或迁移；
- 没有修改固定的 1536 维 Embedding 契约。

## 7. 已知限制

- 当前 Grounding 是“引用集合闭合 + 文本引用标记”校验，不能证明每一个自然语言事实都被文档语义支持；
- 人工编辑复用相同的 Citation marker 校验，但没有额外调用事实核验模型；
- Query Rewrite 和 Generation 各增加一次模型调用，真实端到端 P95 需要在显式启用供应商调用后测量；
- Qwen 的 JSON 输出依赖 OpenAI-compatible `response_format` 支持，供应商异常会走失败/人工处理路径；
- 当前 Graph Checkpointer 仍是单实例内存实现，进程重启后不能恢复待审核执行栈。

## 8. 回滚方法

- 在 Graph 组合边界恢复确定性 Rewriter/Generator；
- 删除 `agent/nodes/` 的生产模型实现；
- 保留阶段二和阶段三的审核与业务持久化能力；
- 不需要数据迁移或知识库重建。

## 9. 下一阶段

阶段五将建立 Agent Evaluation：

- 新增版本化 Agent 数据集；
- 统计 Grounded Answer Rate、Correct Escalation Rate、Citation Validity、误升级率和高风险漏判率；
- 输出 P50/P95 端到端延迟；
- 默认使用可重复的离线执行器；
- 真实检索/模型评测只通过显式参数启用。
