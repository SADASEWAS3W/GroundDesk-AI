# 开发者 A 阶段一报告：现状盘点与 Vector-only 基线

## 1. 执行结论

阶段一已经完成。本阶段只进行了代码、配置、数据库和运行状态检查，并调用现有检索函数完成真实 Vector-only 基线测试，没有修改业务代码、数据库数据或运行配置。

当前检索链路能够正常运行，但还不具备 Hybrid Retrieval 所需的稳定数据契约和离线评测能力。最重要的基线问题是相似度阈值偏低：知识库没有答案的问题仍可能返回弱相关文档，从而让上层 Agent 错误地认为存在可靠依据。

## 2. 执行环境

| 项目 | 当前状态 |
|---|---|
| Git 分支 | `improvements` |
| 基线提交 | `a494c29` |
| API | 运行中，健康检查正常 |
| Web | 运行中，健康检查正常 |
| PostgreSQL | 运行中，健康检查正常 |
| Redis | 运行中，健康检查正常 |
| pgvector | `0.8.6` |
| 知识库文档 | 18 篇 |
| 含 Embedding 的文档 | 18 篇 |
| Embedding API | 真实调用成功 |

工作区在检查开始前已有一份尚未提交的执行方案文档：

```text
docs/developer-a-retrieval-execution-plan.md
```

本阶段保留该改动，没有修改或覆盖用户已有文件。

## 3. 当前检索调用链

当前应用并没有独立的 Retriever Service。检索作为 OpenAI Agents SDK 的 Function Tool 直接注册到 Agent：

```text
Web/API 请求
    ↓
api/main.py
    ↓
agent/customer_success_agent.py::run_agent()
    ↓
OpenAI Agents SDK 根据提示词选择工具
    ↓
agent/tools/knowledge.py::search_knowledge_base()
    ↓
Redis 查询缓存
    ├── 命中：直接返回缓存结果
    └── 未命中：继续执行
            ↓
      通义千问 text-embedding-v4
            ↓
      PostgreSQL/pgvector 余弦检索
            ↓
      相似度阈值过滤 + Top K
            ↓
      写入 Redis，TTL 1 小时
            ↓
      JSON 字符串返回给 Agent
```

当前 Agent 是否执行检索由模型和提示词决定，并非固定的编排节点。

## 4. 数据库和 Embedding 契约

### 4.1 知识库表

当前 `knowledge_base` 表主要字段为：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 主键，可作为稳定文档 ID |
| `title` | VARCHAR(255) | 标题 |
| `content` | TEXT | 正文 |
| `category` | VARCHAR(50) | 分类 |
| `embedding` | VECTOR(1536) | 文档向量 |
| `created_at` | TIMESTAMPTZ | 创建时间 |
| `updated_at` | TIMESTAMPTZ | 更新时间 |

数据库启用了 IVFFlat 索引：

```text
embedding vector_cosine_ops
lists = 10
```

当前共有 18 篇文档，全部具有 Embedding，覆盖 10 个分类。

### 4.2 Embedding 配置

当前容器配置为：

```text
Provider: Alibaba Cloud Model Studio / DashScope OpenAI-compatible API
Model: text-embedding-v4
Dimensions: 1536
Encoding format: float
```

文档入库脚本和查询代码都使用同一模型、相同维度和相同输出格式，因此当前查询向量和文档向量处于同一语义空间。

代码在模块加载及 Embedding 返回后都会校验维度。如果配置或模型返回值不是 1536 维，检索不会继续访问数据库。

## 5. 当前 Vector-only 查询规则

当前默认参数：

```text
top_k = 3
similarity_threshold = 0.25
ivfflat.probes = 10
```

相似度计算：

```sql
1 - (embedding <=> query_vector)
```

其中 `<=>` 是余弦距离，因此：

- 距离越小越相关；
- 转换后的 `similarity` 越大越相关；
- SQL 按距离升序排序；
- 只返回 `similarity >= 0.25` 的文档。

当前结果在日志中记录相似度，但返回给 Agent 的 JSON 会删除以下字段：

- `document_id`；
- `similarity`；
- `rank`；
- 检索耗时；
- 检索策略。

这意味着现有返回结果不足以直接支持 RRF、Reranker、Citation 校验和 Retrieval Eval。

## 6. Vector-only 真实基线

测试时关闭了 Redis 结果复用，保证每个问题都会真实生成 Query Embedding 并查询 pgvector。没有修改或清空 Redis 数据。

| Query | Top 1 | Top 2 | Top 3 | 判断 |
|---|---|---|---|---|
| How do I reset my password? | Password Reset `0.8209` | Login Issues `0.5082` | Account Settings `0.4791` | Top 1 正确 |
| 我忘记密码了，怎么重新设置？ | Password Reset `0.6628` | Login Issues `0.4793` | Account Settings `0.4582` | 跨语言 Top 1 正确 |
| How can I export all my data? | Data Export `0.7416` | Delete Account `0.4451` | Integrations `0.4048` | Top 1 正确 |
| API rate limit 是多少？ | API Documentation `0.6067` | Billing Plans `0.3675` | Slow Performance `0.3435` | Top 1 合理，后两项弱相关 |
| How do I change notification settings? | Notification Settings `0.7112` | Account Settings `0.7061` | 2FA `0.4505` | Top 1 正确，Top 1/2 很接近 |
| I want a full refund | Billing Plans `0.3752` | Invoice `0.3447` | Slow Performance `0.3277` | 没有退款政策，仍返回弱匹配 |
| Can I integrate with Slack? | Integrations `0.6659` | Webhooks `0.5538` | Billing Plans `0.5037` | Top 1 合理，但需核对文档是否明确支持 Slack |
| 你们支持量子计算吗？ | Slow Performance `0.2912` | Getting Started `0.2620` | 无 | 知识库无答案，却被阈值放行 |

以上是基线观察，不代表正式 Recall@3 或 MRR。正式指标需要在阶段六使用带 `relevant_document_ids` 的标注数据集计算。

## 7. 当前测试状态

现有 `tests/test_tools/test_knowledge.py` 已覆盖：

- 默认模型与 1536 维契约；
- 正常召回；
- 无结果；
- 自定义 Top K；
- Embedding 异常；
- 错误向量维度；
- 数据库异常；
- Redis 缓存命中和无 Redis 降级。

本次未能在现有生产容器中执行 pytest，原因是 Dockerfile 使用 `uv sync --no-dev`，镜像内没有安装 `pytest`；当前主机终端也没有可直接调用的 `uv` 命令。

这属于测试运行环境缺失，不是已有测试失败。真实检索基线已通过运行中的 API 容器调用现有函数验证。

后续进入代码实现阶段前，需要选择以下一种测试方式：

1. 在主机安装并使用项目的 `uv`；
2. 增加专门的开发/测试 Docker target；
3. 临时在隔离的测试容器中安装 dev dependencies。

不建议把 pytest 等开发依赖加入生产镜像。

## 8. 已识别问题和风险

### P0：无答案问题可能被误判为有答案

当前阈值为 `0.25`，量子计算问题仍返回两篇无关文章。现有提示词同时要求“只要检索返回文章就不要升级人工”，因此弱召回可能直接转化成错误回答或错误的不升级决策。

阈值不能立即凭单次实验改动。应在阶段六建立 Eval 数据后统一校准。

### P1：返回结果缺少稳定文档 ID

数据库已经有 UUID，但 Function Tool 返回时没有包含它。后续 Citation 无法可靠校验来源，评测也无法通过 ID 判断命中。

### P1：返回结果隐藏全部相关性信号

相似度只写日志，没有进入内部结构。后续 RRF、Reranker、置信度判断和失败分析无法复用。

### P1：检索与 Agent Tool 耦合

Embedding、SQL、缓存、结果格式和 SDK 装饰器都在同一个函数中，难以独立运行三种策略。阶段二应先定义领域模型和 Retriever 接口，不直接重写整个 Agent。

### P1：当前缓存键不包含检索版本和阈值之外的完整策略参数

缓存键目前包含固定版本标记、标准化 Query 和 Top K。引入 Hybrid、RRF、Reranker 或调整阈值后，如果继续共用当前缓存空间，可能得到旧策略结果。下一阶段设计缓存时需要包含检索策略及配置版本。

### P2：种子脚本缺少真正的幂等约束

脚本使用 `ON CONFLICT DO NOTHING`，但知识库表除 UUID 主键外没有标题或业务键唯一约束。再次运行 Seed 时 UUID 会重新生成，理论上可能插入重复文档。这会影响 BM25、RRF 和 Eval。

阶段一没有修改数据库；后续应单独决定使用稳定业务 ID、唯一约束或显式 Upsert。

### P2：没有可直接运行的测试镜像

生产镜像不包含 dev dependencies，当前缺少容器化测试入口。开始阶段二前应先确定测试执行方式。

## 9. 可复用代码与下一阶段边界

可以复用：

- `AgentContext` 中的数据库连接池和模型客户端；
- `database.pool.create_pool()` 及 pgvector codec；
- 现有 Qwen Embedding 调用参数；
- `knowledge_base` 表及 UUID 主键；
- 当前 Redis 容错封装；
- 现有知识库测试 Mock 和 Fixtures。

不应直接复制：

- Function Tool 内联的完整检索逻辑；
- 只返回标题、正文、分类的旧结果结构；
- 仅适用于 Vector-only 的缓存键；
- 未经评测确认的 `0.25` 阈值。

## 10. 阶段二预计文件

阶段二只建立检索契约和 Fake Service，预计新增：

```text
agent/retrieval/__init__.py
agent/retrieval/models.py
agent/retrieval/protocols.py
agent/retrieval/service.py
tests/test_retrieval/test_models.py
tests/test_retrieval/test_service.py
```

预计暂不修改：

```text
api/main.py
agent/customer_success_agent.py
agent/prompts.py
agent/tools/knowledge.py
database/migrations/001_initial_schema.sql
```

阶段二完成后，开发者 B 应能够使用 Fake Service 对接 LangGraph，而现有生产检索路径仍保持不变。

## 11. 阶段一验收结果

- [x] 已确认当前检索调用链；
- [x] 已确认数据库向量列为 `VECTOR(1536)`；
- [x] 已确认文档和 Query 使用同一个 Embedding 模型；
- [x] 已确认余弦距离和相似度方向；
- [x] 已确认知识库共有 18 篇且全部有向量；
- [x] 已运行真实 Vector-only 基线；
- [x] 已记录无答案和弱召回案例；
- [x] 已列出下一阶段预计文件；
- [x] 本阶段未修改业务代码和数据库数据。

阶段一完成，可以在确认本报告后进入阶段二。
