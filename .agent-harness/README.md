# GroundDesk AI Agent Harness

本目录实现面向 AI 二次开发的三层工程治理架构：

```text
第 1 层：rules/                    规定代码应该怎么设计
第 2 层：workflows/ + profiles     规定不同任务至少要做什么
第 3 层：scripts/harness/          提供改动安全性的自动化证据
```

## 使用方法

1. 阅读根目录 `AGENTS.md` 和相关规则。
2. 从 `task-workflow-profiles.json` 选择任务配置与 Lane。
3. 按 `workflows/` 中对应工作流执行。
4. 运行统一门禁：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1
   ```

发布或高风险改动需要执行完整 Docker 构建与健康验证：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/harness/run-all.ps1 -FullDocker
```

验证报告统一写入 `generated/verification/`，该目录不得提交。
