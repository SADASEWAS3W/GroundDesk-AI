# GroundDesk AI Agent 开发规则

本仓库使用 `.agent-harness/` 中定义的三层 Agent Harness。

## 修改代码前

1. 阅读 `.agent-harness/rules/architecture-rules.md` 以及本次改动涉及领域的规则。
2. 使用 `.agent-harness/task-workflow-profiles.json` 判断任务类型和风险等级。
3. 按照 `.agent-harness/workflows/` 中对应的工作流执行。

## 修改代码后

1. 执行任务配置要求的专项检查。
2. 提交前运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1
   ```

3. 如有检查未执行，必须说明原因、剩余风险和后续动作。

## 仓库级强制约束

- 保持依赖方向：`web -> api -> agent/application -> retrieval/tools -> infrastructure`。
- 模型和数据库只能在服务端访问，严禁向 `web/` 暴露模型密钥。
- 当前 Embedding 契约固定为 1536 维；更换模型必须提供全量知识库重建方案。
- Agent 回答必须有知识库依据，否则进入人工审核。
- API 字段变化必须同步修改后端模型、前端类型、API 客户端和契约测试。
- 数据库变化必须包含迁移、数据安全分析和回滚说明。
- 禁止提交 `.env`、密钥、客户数据、缓存、生成报告和本地运行产物。
- 工作区存在用户改动时，必须保留与当前任务无关的改动。

## 规则索引

- `.agent-harness/rules/architecture-rules.md`
- `.agent-harness/rules/agent-rules.md`
- `.agent-harness/rules/rag-rules.md`
- `.agent-harness/rules/api-contract-rules.md`
- `.agent-harness/rules/security-rules.md`
