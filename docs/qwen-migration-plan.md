# 通义千问迁移设计与实施计划

## 1. 文档状态

- 状态：待审查
- 目标分支：`improvements`
- 本文档只定义修改方案，不代表已经实施。
- 在方案获得确认前，不修改模型调用、数据库数据或运行配置。

## 2. 背景

项目当前使用 OpenAI Agents SDK 组织 Agent、Runner 和函数工具，并通过 OpenAI API 完成两类模型调用：

1. 使用 `gpt-4o` 驱动客服 Agent 和工具调用。
2. 使用 `text-embedding-3-small` 生成知识库与查询向量。

知识库向量字段固定为 PostgreSQL `VECTOR(1536)`。迁移目标是使用阿里云百炼的通义千问模型，同时保留现有 OpenAI Agents SDK、工具体系、FastAPI、Redis、PostgreSQL 和 1536 维 pgvector 结构。

## 3. 目标

- 使用通义千问作为 Agent 的对话与工具调用模型。
- 使用百炼的 OpenAI 兼容接口，尽量减少 SDK 层改动。
- 使用通义千问 Embedding，并显式生成 1536 维向量。
- 保持数据库字段 `VECTOR(1536)` 不变。
- 保留现有 11 个 Agent 工具及业务流程。
- 支持通过环境变量切换模型、接口地址和向量模型。
- 避免将 API Key 写入源码、镜像或 Git 仓库。
- 为模型请求、向量生成和知识库搜索提供可验证的错误处理。

## 4. 非目标

- 本次不重写前端页面。
- 本次不替换 FastAPI、Redis、PostgreSQL 或 pgvector。
- 本次不引入新的向量数据库。
- 本次不接入 Gmail/Twilio 的真实出站发送。
- 本次不改变现有工单、客户和对话数据模型。
- 本次不同时维护 OpenAI 与通义千问两套生产向量空间。

## 5. 目标架构

```text
Web / Gmail / WhatsApp
          |
          v
       FastAPI
          |
          v
OpenAI Agents SDK (Agent / Runner / function_tool)
          |
          +--> Qwen Chat Model
          |    - OpenAI-compatible endpoint
          |    - Agent reasoning and tool calling
          |
          +--> Qwen Embedding Model
               - OpenAI-compatible embeddings endpoint
               - Explicit dimensions=1536
                         |
                         v
               PostgreSQL + pgvector
               knowledge_base.embedding VECTOR(1536)
```

## 6. 模型与接口选择

### 6.1 对话模型

默认建议：`qwen-plus`。

原因：客服 Agent 需要稳定的指令遵循、函数工具调用、中文理解和合理的成本/延迟平衡。具体模型名称必须可通过环境变量覆盖，避免写死在代码中。

### 6.2 Embedding 模型

默认建议：`text-embedding-v4`，调用时显式传递 `dimensions=1536`。

备选：支持输出 1536 维的其他百炼 Embedding 模型。无论选择哪个模型，都必须满足以下约束：

- 输出维度严格等于 1536。
- 查询向量与知识库文章向量使用相同模型和相同维度。
- 更换 Embedding 模型后必须重新生成全部知识库向量。

### 6.3 Agents SDK 接入策略

优先采用 `OpenAIChatCompletionsModel` 配合自定义 `AsyncOpenAI` 客户端：

```python
qwen_client = AsyncOpenAI(
    api_key=settings.dashscope_api_key,
    base_url=settings.dashscope_base_url,
)

qwen_model = OpenAIChatCompletionsModel(
    model=settings.qwen_chat_model,
    openai_client=qwen_client,
)
```

选择 Chat Completions 适配层的原因是其在 OpenAI 兼容提供商中的兼容面通常更明确。实施阶段会用真实工具调用做集成验证；如果当前 SDK 版本和百炼 Responses API 的组合验证更稳定，可在不改变业务接口的前提下切换到 Responses 适配方式。

## 7. 配置设计

新增以下环境变量：

```env
# Alibaba Cloud Model Studio / DashScope
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1

# Qwen models
QWEN_CHAT_MODEL=qwen-plus
QWEN_EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1536

# Disable OpenAI-hosted tracing when no OpenAI API key is used
AGENTS_TRACING_DISABLED=true
```

配置规则：

- `DASHSCOPE_API_KEY` 必填，不提供默认值。
- `DASHSCOPE_BASE_URL` 必填，并应与 API Key 所属地域及业务空间一致。
- `EMBEDDING_DIMENSIONS` 默认 1536；启动时如果不是 1536，应直接报配置错误。
- `.env` 继续被 `.gitignore` 忽略。
- `.env.example` 只保存占位符，不保存真实 Key 或 Workspace ID。
- Docker Compose 通过变量引用把配置传入 API 容器。

## 8. 代码修改清单

### 8.1 `agent/context.py`

当前问题：

- 客户端只接受 OpenAI Key。
- 没有显式设置百炼 `base_url`。
- 上下文属性命名为 `openai_client`，与迁移后的实际提供商不符。

计划修改：

- 从环境变量读取 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL`。
- 创建指向百炼兼容端点的 `AsyncOpenAI` 客户端。
- 将上下文属性重命名为中性的 `model_client`，或在兼容阶段保留旧属性并增加弃用说明。
- 对缺失配置给出不包含密钥内容的明确错误。

### 8.2 `agent/customer_success_agent.py`

当前问题：Agent 仅通过字符串模型名使用 SDK 默认 OpenAI 提供商。

计划修改：

- 使用百炼客户端构造 `OpenAIChatCompletionsModel`。
- 从 `QWEN_CHAT_MODEL` 读取模型名称。
- 保留现有 `SYSTEM_PROMPT`、`ALL_TOOLS` 和 `Runner.run` 调用结构。
- 在没有 OpenAI Key 时禁用 OpenAI tracing，避免 tracing 请求返回 401。

需要验证：

- 多轮工具调用。
- 工具参数 JSON 生成。
- 工具执行结果回传。
- Agent 最终输出文本。
- 最大轮次和异常行为。

### 8.3 `agent/tools/knowledge.py`

当前问题：Embedding 模型写死为 `text-embedding-3-small`。

计划修改：

- 从 `QWEN_EMBEDDING_MODEL` 读取模型名。
- Embedding 请求显式传递 `dimensions=1536` 和 `encoding_format="float"`。
- 验证响应向量长度；不是 1536 时禁止执行 SQL 查询并记录安全错误。
- 保留余弦相似度查询和 pgvector 索引。
- 切换模型后重新评估 `_SIMILARITY_THRESHOLD = 0.25`，不直接假设旧阈值仍然最优。

### 8.4 `database/migrations/002_seed_knowledge_base.py`

当前问题：初始化脚本直接创建默认 OpenAI 客户端，并写死 OpenAI Embedding 模型。

计划修改：

- 使用与运行时相同的百炼客户端配置。
- 使用与查询端相同的模型、维度和编码格式。
- 写入前验证每条向量维度。
- 增加清晰的失败提示，但不记录 API Key。
- 使重复执行策略明确，避免旧模型向量和新模型向量混用。

### 8.5 `database/migrations/001_initial_schema.sql`

计划：保留 `embedding VECTOR(1536)`，无需修改字段维度。

可选增强：新增记录 Embedding 模型版本的字段或元数据表，例如：

```sql
embedding_model VARCHAR(100)
```

首轮实施建议暂不修改表结构，而是通过迁移脚本保证全量重建一致性；如果需要长期支持模型升级，再增加模型版本字段。

### 8.6 `docker-compose.yml`

计划修改 API 服务的环境变量：

```yaml
environment:
  DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD:-postgres}@postgres:5432/crm
  REDIS_URL: redis://redis:6379
  DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
  DASHSCOPE_BASE_URL: ${DASHSCOPE_BASE_URL}
  QWEN_CHAT_MODEL: ${QWEN_CHAT_MODEL:-qwen-plus}
  QWEN_EMBEDDING_MODEL: ${QWEN_EMBEDDING_MODEL:-text-embedding-v4}
  EMBEDDING_DIMENSIONS: ${EMBEDDING_DIMENSIONS:-1536}
  AGENTS_TRACING_DISABLED: ${AGENTS_TRACING_DISABLED:-true}
```

### 8.7 `.env.example`

计划：用百炼配置替换 OpenAI 必填配置，并保留清晰占位符。真实 `.env` 不提交。

### 8.8 测试代码

预计修改：

- `tests/conftest.py`
- `tests/test_agent/test_agent.py`
- `tests/test_tools/test_knowledge.py`
- `tests/test_database/test_seed.py`
- 必要时修改 API 测试中的上下文 mock。

Mock 名称应从 OpenAI 专用命名调整为 provider-neutral 命名，同时验证请求包含正确的模型名和 `dimensions=1536`。

## 9. 数据迁移方案

### 9.1 为什么必须重建向量

不同 Embedding 模型生成的向量不在同一语义空间。即使维度同为 1536，也不能将 OpenAI 生成的文章向量与千问生成的查询向量混合比较。

### 9.2 开发环境方案

如果当前数据库没有需要保留的数据：

1. 停止服务。
2. 删除开发数据库卷。
3. 重新创建数据库结构。
4. 使用千问 Embedding 重新导入知识库。
5. 启动 API 并执行搜索验收。

删除 Docker 数据卷属于破坏性操作，实施前必须再次确认。

### 9.3 保留业务数据方案

如果客户、工单和对话数据必须保留：

1. 备份数据库。
2. 仅将 `knowledge_base.embedding` 置空或重建知识库记录。
3. 使用千问模型批量生成 1536 维文章向量。
4. 在事务或可恢复批次中更新。
5. 验证不存在空向量、错误维度或模型混用。

不得为了重建知识库向量而删除客户、工单、消息和指标数据。

## 10. 缓存迁移

Redis 中可能存在使用旧 Embedding 搜索结果产生的知识库缓存。切换模型后应清除相关 KB 搜索缓存，避免继续返回旧结果。

计划采用命名空间版本升级，例如把 KB 缓存 Key 从旧版本切换到新版本，而不是对整个 Redis 执行无范围删除。这样不会误删异步任务状态或其他缓存。

## 11. 安全设计

- 不在源码、测试快照、日志、Dockerfile 或 Git 历史中写入真实 Key。
- 日志只报告配置项名称和错误类型，不记录请求认证头。
- `.env` 必须保持在 `.gitignore` 中。
- 生产环境应使用平台 Secret/Kubernetes Secret，而不是提交明文配置。
- `k8s/secret.yml` 仅保留占位符或模板。
- 不把 `DASHSCOPE_API_KEY` 暴露给 Next.js 客户端。

## 12. 错误处理

需要覆盖以下情况：

- Key 缺失或无效。
- Base URL 与地域/业务空间不匹配。
- 对话模型不存在或无调用权限。
- 模型不支持所需工具调用行为。
- Embedding 模型不存在或无权限。
- Embedding 返回维度不是 1536。
- 百炼接口限流、超时或临时不可用。
- PostgreSQL 或 Redis 不可用。

对外错误应保持简洁，不暴露提供商响应中的敏感信息；内部日志保留 correlation ID 方便排查。

## 13. 测试计划

### 13.1 单元测试

- 正确读取百炼环境变量。
- 缺少 Key/Base URL 时快速失败。
- Agent 使用配置的千问模型。
- Embedding 请求包含正确模型和 `dimensions=1536`。
- 非 1536 维响应被拒绝。
- Embedding API 异常时返回知识库不可用，而不是生成错误答案。
- tracing 禁用逻辑生效。

### 13.2 集成测试

- 使用真实百炼 Key 请求一次简单对话。
- 执行至少一次真实函数工具调用。
- 为样例文章生成 1536 维向量。
- 使用语义相近但关键词不同的问题搜索到正确文章。
- 无匹配问题触发现有升级人工流程。

真实 API 测试默认不放入普通 CI，避免产生费用和依赖外部服务；可通过显式环境开关执行。

### 13.3 回归测试

- 后端现有 pytest 测试通过。
- 前端 Vitest 测试通过。
- Docker Compose 四个服务健康。
- `/health`、`/health/live`、`/health/ready` 正常。
- Web 表单可以提交、轮询并显示最终回复。

## 14. 验收标准

满足以下条件才视为迁移完成：

- 项目无需 `OPENAI_API_KEY` 即可启动并处理客服请求。
- Agent 实际调用配置的通义千问对话模型。
- 现有函数工具工作流可以完成。
- 知识库文章和查询均使用同一个千问 Embedding 模型。
- 所有向量长度严格为 1536。
- 数据库继续使用 `VECTOR(1536)`。
- 不存在 OpenAI/千问向量混用。
- 单元测试和前端测试通过。
- Docker Compose 启动及健康检查通过。
- Git 中不存在真实 API Key。

## 15. 回滚方案

代码回滚：

- 迁移修改放在独立提交中，可通过正常 Git revert 回滚。
- 不使用 `git reset --hard` 覆盖用户工作。

数据回滚：

- 操作知识库前创建数据库备份。
- 如果仅替换知识库向量，可从备份恢复 `knowledge_base`。
- Redis 使用缓存命名空间版本切换，回滚时恢复旧命名空间即可。

配置回滚：

- 恢复原 OpenAI 配置后，还必须恢复与 OpenAI Embedding 模型匹配的知识库向量，不能只切换 Key 和模型名。

## 16. 实施顺序

1. 增加配置解析和校验。
2. 创建百炼兼容客户端。
3. 将 Agent 接入千问对话模型。
4. 将运行时知识库查询接入千问 Embedding。
5. 修改知识库初始化脚本。
6. 更新 Docker Compose、`.env.example` 和部署模板。
7. 更新单元测试与 mock。
8. 运行不需要真实 Key 的完整测试。
9. 经授权后使用现有 `DASHSCOPE_API_KEY` 做最小真实调用验证。
10. 经再次确认后重建开发知识库向量和清理对应缓存。
11. 启动完整 Docker 环境并执行端到端验收。

## 17. 审查时需要确认的决策

开始实施前，请确认以下事项：

1. 对话模型默认使用 `qwen-plus` 是否可以。
2. Embedding 默认使用 `text-embedding-v4`、维度 1536 是否可以。
3. 是否完全移除运行时对 `OPENAI_API_KEY` 的依赖，还是保留 OpenAI/Qwen 双提供商切换能力。
4. 当前开发数据库是否包含必须保留的客户、工单或对话数据。
5. 是否允许在代码和 mock 测试完成后，使用电脑环境中现有的 `DASHSCOPE_API_KEY` 发起少量真实验证请求（可能产生少量费用）。

## 18. 官方参考

- [阿里云百炼：OpenAI Chat 接口兼容](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- [阿里云百炼：文本向量接口与维度](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)
- [阿里云百炼：OpenAI Responses 兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses)
