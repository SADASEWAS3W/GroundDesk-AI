# GroundDesk AI Agent 开发规则

本仓库使用 `.agent-harness/` 中定义的三层 Agent Harness。

## 修改代码前

1. 阅读 `.agent-harness/rules/architecture-rules.md`、`.agent-harness/rules/verification-rules.md` 以及本次改动涉及领域的规则。
2. 使用 `.agent-harness/task-workflow-profiles.json` 判断任务类型和风险等级。
3. 按照 `.agent-harness/workflows/` 中对应的工作流执行。

## 分阶段实施与最终验证

1. 同一用户任务可以拆为多个实现阶段。阶段结束只记录进展、变更范围和待验证项，不要求每阶段运行测试、专项检查或完整 Harness。
2. 所有阶段的代码、测试代码和文档修改完成后，在最终交付前统一执行一轮验证；合并任务涉及的 Profile 门禁与专项验收项，去重执行。
3. 提交前所需的统一入口也安排在这轮最终验证中，不在各阶段重复运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1
   ```

4. 排障时可以按需运行最小检查，但不能把阶段检查变成固定流程。破坏性操作前的目标核对、备份、授权及运行时安全校验不得推迟。
5. 验证失败后只补跑失败项及修复影响到的检查；最终验证后有新改动时，相关结果失效，必须补验。没有新改动时不因汇报或提交重复整轮验证。
6. 阶段内未运行的检查标记为“待最终验证”，不能声称已通过。最终仍未执行的检查必须说明原因、剩余风险和后续动作。

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
- `.agent-harness/rules/verification-rules.md`（验证时机的统一规则，适用于所有 Profile 和工作流）
- `.agent-harness/rules/agent-rules.md`
- `.agent-harness/rules/rag-rules.md`
- `.agent-harness/rules/api-contract-rules.md`
- `.agent-harness/rules/security-rules.md`
- `.agent-harness/rules/collaboration-rules.md`（双人开发任务必须读取；不得假设另一位开发者的实现状态，触及共享边界前必须通知用户）
