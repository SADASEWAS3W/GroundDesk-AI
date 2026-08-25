# API 契约规则

- FastAPI 请求和响应模型是后端契约的权威来源。
- 公开字段变化必须同步修改 Pydantic 模型、OpenAPI 行为、`web/src/lib/types.ts`、`web/src/lib/api.ts` 和集成测试。
- 已有字段不得在不声明的情况下改变语义或类型。
- 异步任务必须使用明确状态，例如 `processing`、`completed`、`failed`、`waiting_review`。
- 人工审核接口必须幂等，并返回操作后的工作流状态。
- 对外错误不得暴露堆栈、SQL、供应商原始载荷或密钥。
- Correlation ID 或 Run ID 必须贯穿 API、后台任务、日志和审核操作。
- 新接口至少测试成功、参数校验和依赖失败；需要鉴权时还要测试权限策略。
