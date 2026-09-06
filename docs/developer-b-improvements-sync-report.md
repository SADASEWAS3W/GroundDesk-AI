# Developer B：improvements 分支同步报告

日期：2026-09-06

同步提交：`2e64300 新增数据集`

同步方式：`main` 快进到 `origin/improvements`

## 1. 同步结论

`origin/improvements` 的新增提交已经以 Fast-forward 方式并入本地 `main`，没有产生合并提交或文件冲突。同步前已有的 Developer B 未提交改动全部保留；本地 `main` 当前比 `origin/main` 领先 1 个提交，尚未推送。

## 2. 本次引入的内容

- 新增 `retrieval_v2.jsonl`：300 条确定性构造的 Retrieval Eval 数据，其中 240 条可回答、60 条 no-answer；按 tuning/validation/test 划分为 180/60/60。
- 新增 `build_retrieval_v2.py`：用于确定性重建 v2 数据集。
- 新增 `rerank_replay.py`：支持基于已有检索报告进行离线 rerank replay。
- 扩展 `retrieval_eval.py`：支持有界并发、向量检索失败重试、运行故障统计，以及 raw/accepted 两组指标。
- 扩展数据集契约：Retrieval Eval 允许冻结的 `test` split。
- 增加 v2 数据集与 rerank replay 的自动化测试。

## 3. 与 Developer B 改动的兼容性

同步提交修改的是 Retrieval Eval 相关文件，没有与当前未提交的 Agent、Application Service、Review、API 或 Web 文件发生同路径覆盖。

Retrieval Eval 与 Agent Eval 使用独立的数据加载器和命令入口：

- Retrieval：`evals.dataset`、`evals.retrieval_eval`
- Agent：`evals.agent_dataset`、`evals.agent_eval`

因此 Retrieval v2 新增的 `test` split 不会改变 Agent Eval 当前的 tuning/validation 契约。

## 4. 验证结果

同步后执行：

```text
pytest: 334 passed, 4 skipped
vitest: 13 files passed, 87 tests passed
eslint: passed
next production build: passed
secret scan: passed
architecture boundary: passed
embedding contract: passed (1536 dimensions)
git diff --check: passed
Linux run-all.sh: passed
```

后端仅保留 LangGraph Checkpoint serializer 的上游未来默认值警告；前端仍有既有的 React `act(...)` 与 jsdom Canvas 提示，不影响测试通过。

仓库现已提供与 PowerShell 入口等价的 Linux Harness：`scripts/harness/run-all.sh`。默认执行三项静态门禁、后端测试、前端测试和 Compose 配置检查；使用 `--full-docker` 可进一步执行 Compose 构建、健康检查和 HTTP 冒烟测试。

## 5. 未执行项与风险

- 当前没有 `.env`，运行环境中也没有 `DATABASE_URL`、`DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL`。诊断时本地 PostgreSQL 可以健康启动，但 `knowledge_base` 和已有 Embedding 均为 0 条，因此无法运行有效的 Retrieval v2 Live Eval。
- v2 是确定性合成数据集，适合回归与调参隔离，不能代替经过匿名化和人工复核的真实生产查询。
- 本次只完成本地同步与验证，没有推送 `main`，也没有提交工作区中的 Developer B 改动。

## 6. 后续建议

1. 从 `.env.example` 创建不入库的 `.env`，填写真实 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL` 和本地或远程 `DATABASE_URL`。
2. 启动 PostgreSQL 并执行知识库种子脚本，确认文档 Embedding 为 1536 维，再跑 Retrieval v2 Live Eval。
3. 用 tuning split 的 top-1 Vector 分数校准拒答阈值；`raw_metrics` 用于比较检索/排序能力，`accepted_metrics` 用于评估阈值应用后的有效覆盖，不能把两者当成同一条基线。
4. 使用 validation 验证冻结阈值，最终只在 test split 上做一次验收，并把生成报告留在被 Git 忽略的 `evals/reports/`。
