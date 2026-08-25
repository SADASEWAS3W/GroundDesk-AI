# 架构规则

## 依赖方向

```text
web -> api -> agent/application -> retrieval/tools -> database/cache/model provider
```

- `web/` 只能通过 `web/src/lib/api.ts` 调用后端。
- `api/` 负责传输层校验和响应映射，不得包含业务 SQL 或模型 Prompt。
- `agent/` 负责工作流编排、Prompt、状态、工具和模型调用抽象。
- 检索能力增长后应进入独立 retrieval 模块，检索代码不得依赖 HTTP。
- `database/` 负责连接池、编解码、迁移和持久化，不得导入 `agent` 或 `api`。
- Redis、PostgreSQL 和模型客户端必须在组合边界创建，并通过上下文注入。

## 修改边界

- 优先增加职责单一的模块，避免持续扩大 `api/main.py` 或 `agent/customer_success_agent.py`。
- 共享契约只能有一个权威定义，其他层通过显式适配器使用。
- 除配置元数据外，领域模型不得依赖具体模型供应商名称。
- 跨层修改必须执行 API 契约检查并记录端到端验证结果。

## 二次开发目标结构

```text
agent/
  state.py              共享工作流状态
  graph.py              LangGraph 图定义
  nodes/                查询改写、生成、Grounding、人工审核
  retrieval/            Vector、BM25、融合、重排
evals/                  Retrieval Eval 与 Agent Eval
```

共享状态和公开 API 契约发生不兼容变化前必须先审查方案。
