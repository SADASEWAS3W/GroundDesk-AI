# GroundDesk AI Agent Harness

本目录实现面向 AI 二次开发的三层工程治理架构：

```text
第 1 层：rules/                    规定设计约束和任务级最终验证规则
第 2 层：workflows/ + profiles     分阶段实现，累计、去重最终验收项
第 3 层：scripts/harness/          全部阶段完成后统一执行一轮验证
```

## 使用方法

1. 阅读根目录 `AGENTS.md` 和相关规则。
2. 从 `task-workflow-profiles.json` 选择任务配置与 Lane。
3. 按 `workflows/` 分阶段实现，同时编写测试和文档，阶段内只记录待验证项，不必每阶段跑测试或门禁。
4. 全部阶段完成后，按照 `rules/verification-rules.md` 合并、去重 Profile 和领域专项检查，在最终交付前统一验证一次。需要提交前统一门禁时，在这一轮运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1
   ```

发布或高风险改动需要完整 Docker 构建与健康验证时，在同一最终轮次使用下面的入口替代上面的入口，不重复运行两者：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1 -FullDocker
```

`verificationPolicy` 是 Agent/开发者遵循的编排配置，不是后台自动调度器；脚本保持显式调用，门禁内容没有删减。排障可按需做最小检查，危险操作的安全前置条件仍须先满足。失败或后续修复仅补验失败项及受影响项。

验证报告按整个任务汇总写入 `generated/verification/`，无需每阶段生成报告，该目录不得提交。
