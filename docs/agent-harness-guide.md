# GroundDesk AI Agent Harness 使用说明

## 1. 文档目的

本项目使用三层 Agent Harness 管理后续二次开发，目标是让开发人员和 AI Agent 在修改代码时遵守同一套规则、执行与风险匹配的工作流，并通过自动化门禁提供可验证的交付证据。

三层架构不是 Web、Service、Database 这类业务代码分层，而是覆盖整个开发过程的工程治理体系：

```text
第 1 层：规范约束层——规定代码应该怎么写
第 2 层：工作流编排层——规定不同任务至少要做什么
第 3 层：自动验证层——证明改动是否满足质量要求
```

## 2. 目录结构

```text
AGENTS.md                              # Agent/Codex 统一入口
.agent-harness/
├── README.md                          # Harness 快速说明
├── task-workflow-profiles.json        # 任务 Profile、Lane 和门禁映射
├── rules/                             # 第 1 层：规范约束
│   ├── architecture-rules.md
│   ├── agent-rules.md
│   ├── rag-rules.md
│   ├── api-contract-rules.md
│   └── security-rules.md
├── workflows/                         # 第 2 层：工作流编排
│   ├── bugfix.md
│   ├── feature-development.md
│   ├── rag-change.md
│   ├── api-contract-change.md
│   └── database-migration.md
└── templates/
    ├── verification-report.md         # 验证报告模板
    └── iteration-ledger.example.json  # 迭代台账示例
scripts/harness/                        # 第 3 层：自动验证
├── check_secrets.py
├── check_architecture.py
├── check_embedding_contract.py
├── run-backend-tests.ps1
├── run-frontend-tests.ps1
├── verify-compose.ps1
└── run-all.ps1
```

## 3. 第一层：规范约束层

第一层解决“代码应该怎么设计”的问题。

### 3.1 架构规则

项目依赖方向固定为：

```text
web
  ↓
api
  ↓
agent/application
  ↓
retrieval/tools
  ↓
database/cache/model provider
```

主要约束：

- 前端只通过集中式 API Client 调用后端。
- FastAPI 只处理传输层校验和响应映射，不承载 Prompt 或业务 SQL。
- Agent 层负责模型编排、状态、工具和路由。
- Database 层不得反向依赖 Agent 或 API。
- 模型、数据库和 Redis 客户端通过上下文注入，不在业务函数内分散创建。

### 3.2 Agent 规则

- Agent 只能通过注册工具或注入接口访问外部状态。
- Prompt 中的工具名称必须与工具注册和测试保持一致。
- 工具失败不能被包装成成功回答。
- 高风险操作、证据不足和 Grounding 失败必须进入人工审核。
- HITL 审批和恢复必须幂等，防止重复副作用。

### 3.3 RAG 规则

- 查询和文档必须使用同一个 Embedding 模型。
- 当前数据库向量契约固定为 `VECTOR(1536)`。
- 每次 Embedding 请求都必须显式请求并校验 1536 维。
- 更换 Embedding 模型必须全量重建知识库向量并升级缓存版本。
- Citation 只能引用当前检索流程真实返回的文档。
- 没有可靠证据时不得输出 Grounded Answer。

### 3.4 API 契约规则

API 字段变化必须同步修改：

1. 后端 Pydantic 请求/响应模型。
2. FastAPI 接口行为。
3. `web/src/lib/types.ts`。
4. `web/src/lib/api.ts`。
5. 后端与前端集成测试。

### 3.5 安全规则

- 禁止提交 `.env`、API Key、密码、Token 和数据库备份。
- 模型密钥不能进入 `NEXT_PUBLIC_*` 或浏览器代码。
- 日志不能输出认证头、完整密钥或不必要的客户隐私数据。
- 破坏性操作必须校验目标、获得授权并提供恢复方案。

## 4. 第二层：工作流编排层

第二层解决“这次任务至少要做到什么程度”的问题。

### 4.1 Lane 风险分级

| Lane | 使用场景 | 最低要求 |
|------|----------|----------|
| L0 | 分析、文档、重复任务、输入不足 | 分析、说明、报告 |
| L1 | 局部低风险 UI、文案或测试 | 影响检查、修改、局部测试 |
| L2 | 标准功能、API 或普通 Bug | 方案、实现、单元测试、契约验证 |
| L3 | Agent、RAG、模型、数据库、安全、部署 | 方案审批、完整影响分析、回归、E2E、人工验收 |

风险判断不只看修改文件数量。例如只改一行 Embedding 模型名，也会影响整个知识库语义空间，因此属于 L3。

### 4.2 Profile 选择

任务与 Profile 的常用映射：

| 任务 | Profile | 默认 Lane |
|------|---------|-----------|
| 只写文档 | `documentation` | L0 |
| 局部 Bug | `simple-bug` | L1 |
| 普通功能 | `standard-feature` | L2 |
| API 字段变化 | `api-contract-change` | L2 |
| RAG 或 Agent 修改 | `rag-or-agent-change` | L3 |
| 数据库迁移 | `database-migration` | L3 |
| 更换模型供应商 | `model-provider-change` | L3 |
| 正式发布 | `release` | L3 |

具体映射和必跑门禁以 `.agent-harness/task-workflow-profiles.json` 为准。

### 4.3 五类工作流

#### Bug 修复

```text
复现 → 定位 → 风险定级 → 回归测试 → 最小修复 → 验证 → 记录根因
```

#### 功能开发

```text
目标与非目标 → 契约 → Lane → 接口与测试 → 分层实现 → E2E → 文档
```

#### RAG/Agent 变更

```text
模型与向量契约 → 检索接口 → 测试 → 数据/缓存迁移
→ Retrieval Eval → Agent Eval → 真实模型最小验证
```

#### API 契约变更

```text
新旧契约 → 后端模型 → 前端类型/API Client
→ 两端测试 → OpenAPI → Compose 验证
```

#### 数据库迁移

```text
影响与回滚 → 备份 → 新迁移 → 空库测试
→ 旧版本升级测试 → 完整性检查 → Compose 验证
```

## 5. 第三层：自动验证层

第三层解决“如何证明修改安全”的问题。

### 5.1 密钥扫描

```powershell
python scripts/harness/check_secrets.py
```

检查 Git 已跟踪文件和待提交文件中的常见 API Key、Token、密码和私钥。示例占位符不会被误判为真实密钥。

### 5.2 架构边界检查

```powershell
python scripts/harness/check_architecture.py
```

当前检查包括：

- `database` 不得导入 `agent` 或 `api`。
- `agent` 不得导入 `api`。
- API 层不得直接导入 `asyncpg` 或放置业务 SQL。
- 允许健康检查通过注入的连接池执行 `SELECT 1`。

### 5.3 Embedding 契约检查

```powershell
python scripts/harness/check_embedding_contract.py
```

检查以下位置是否统一为 1536 维：

- PostgreSQL Schema。
- `.env.example`。
- Agent 查询 Embedding。
- 知识库初始化脚本。
- Docker Compose。

### 5.4 后端测试

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/run-backend-tests.ps1
```

脚本优先使用本地 `uv` 或 `.venv`；环境不满足时可使用 Docker 中的 Python 3.12 执行。

强制使用 Docker：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/run-backend-tests.ps1 -UseDocker
```

### 5.5 前端测试

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/run-frontend-tests.ps1
```

本地 Node.js 版本低于 20.19 时，脚本自动使用 `node:22-alpine`，避免本地运行时版本不兼容。

### 5.6 Compose 检查

只验证配置：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/verify-compose.ps1
```

完整构建、启动、健康检查和 HTTP 冒烟测试：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/verify-compose.ps1 -Full
```

## 6. 统一执行入口

日常开发建议执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1 -UseDockerForTests
```

该命令依次运行：

```text
密钥扫描
→ 架构边界检查
→ Embedding 契约检查
→ 后端测试
→ 前端测试
→ Compose 配置检查
```

L3 或发布前执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1 -UseDockerForTests -FullDocker
```

## 7. 二次开发示例

### 示例一：新增 Citation 字段

1. 选择 `api-contract-change`，默认 L2。
2. 阅读架构、Agent、RAG 和 API 契约规则。
3. 修改后端响应模型。
4. 修改前端 TypeScript 类型和 API Client。
5. 增加后端和前端集成测试。
6. 运行统一门禁。

如果 Citation 同时改变生成、Grounding 或人工审核逻辑，应升级为 L3。

### 示例二：加入 BM25 + RRF

1. 选择 `rag-or-agent-change`，Lane 为 L3。
2. 先定义 Vector、BM25、Fusion 和 Reranker 接口。
3. 保留现有 pgvector 作为一路召回。
4. 增加 Retrieval Eval 基线。
5. 对比 Recall@3 和 MRR。
6. 执行全部门禁和端到端演示。

### 示例三：更换 Embedding 模型

1. 选择 `model-provider-change`，Lane 为 L3。
2. 确认新模型支持 1536 维。
3. 设计全量知识库向量重建方案。
4. 升级 Redis 检索缓存命名空间。
5. 准备数据库备份和回滚方案。
6. 重新评估检索阈值。
7. 执行 Retrieval Eval、后端测试和完整 Compose 门禁。

## 8. 验证报告

每个 L2/L3 任务建议按 `.agent-harness/templates/verification-report.md` 记录：

- 任务 Profile 和 Lane。
- 修改范围与契约变化。
- 数据迁移情况。
- 通过的测试与门禁。
- 跳过的检查及原因。
- 真实模型验证。
- 已知限制和回滚方法。

报告可保存到：

```text
generated/verification/<任务名称>.md
```

`generated/verification/` 已加入 `.gitignore`，避免临时验证记录污染仓库。

## 9. 与二次开发计划的关系

`docs/two-person-development-plan.md` 描述功能建设内容，例如 LangGraph、Hybrid Retrieval、Reranker、Citation、Grounding、HITL 和 Evaluation。

Agent Harness 负责约束这些功能如何安全落地：

```text
二次开发计划：决定做什么
Agent Harness：决定怎么做、做到什么程度、如何证明完成
```

建议后续每个功能阶段都先选择 Profile 和 Lane，再按 Harness 工作流实施。

## 10. 维护规则

- 新增重要架构约束时更新 `rules/`，不要只写在聊天记录中。
- 出现重复开发流程时再新增 Workflow，避免工作流数量无序增长。
- 自动检查必须尽量无副作用，不能写入业务数据或泄露密钥。
- 修改门禁脚本时必须先在当前仓库基线上验证，避免大量误报。
- 规则、工作流和脚本发生变化时同步更新本文档。
