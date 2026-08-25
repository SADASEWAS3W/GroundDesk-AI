# RAG 与 Agent 变更工作流

本工作流默认属于 L3。

1. 记录当前及目标模型、维度、检索阶段、阈值和缓存版本。
2. 判断旧向量是否兼容；维度相同不代表语义空间相同。
3. 定义 Vector、BM25、融合、重排、生成、Citation、Grounding 和人工审核接口。
4. 覆盖成功、无证据、供应商失败、维度错误、Citation 无效和升级人工测试。
5. 更换 Embedding 时准备备份、全量重建、缓存迁移和回滚方案。
6. 对比基线与候选检索效果：Recall@3、MRR 和失败案例。
7. 执行 Agent Eval：Grounded Answer Rate、Correct Escalation Rate 和工具/路由正确率。
8. 仅在具备凭据和费用授权时执行最小真实供应商测试。
9. 运行全部 Harness 门禁并记录已知限制。
