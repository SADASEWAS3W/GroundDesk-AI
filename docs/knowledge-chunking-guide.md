# 长文档切片与知识库导入

独立长文档语料和来源/证据标签评测现已补充，见 [长文档对照评测指南](long-document-evaluation-guide.md)。原有知识库和运行时阈值未切换。

## 1. 交付范围与当前状态

新增一条可选的 UTF-8 文本 / Markdown 导入路径：段落优先切片、重叠上下文、标题加片段正文向量化、事务入库、切片来源追溯。原有种子入库脚本和线上检索默认配置保持兼容。

本次按 Harness 的 RAG / 数据库 L3 流程开发。迁移仅在临时 PostgreSQL 中验证，未对用户知识库执行迁移或重建，未调用付费模型。

| 模块 | 文件 |
|---|---|
| 切片算法 | [chunking.py](../agent/retrieval/chunking.py) |
| 预览、向量化、导入入口 | [ingest.py](../agent/retrieval/ingest.py) |
| 参数化 SQL 与事务持久化 | [knowledge_ingestion.py](../database/knowledge_ingestion.py) |
| 增量迁移 | [003_knowledge_chunk_provenance.sql](../database/migrations/003_knowledge_chunk_provenance.sql) |

## 2. 切片规则

初始参数是 `chunk_size=1200`、`overlap=150`，单位为 Python 字符串字符，不是 token。这些是可运行的起始参数，尚未通过业务评测确定为最优值。

1. 短文档保留为单个片段；纯空白文档不允许入库。
2. 长文档每次取不超过 chunk_size 的窗口。
3. 在窗口后半部分优先寻找最后一个空行段落边界。
4. 没有段落边界时寻找句末标点，再尝试空白边界；都没有则在窗口末尾硬切。
5. 下一片从上一片末尾向前回退 overlap 个字符开始。
6. 保留原文切片内容和起止位置，不对每片 strip；末尾不重复生成完全被覆盖的片段。

重叠小于窗口一半，以保证每轮向前推进；片段序号从 0 开始，结束偏移为右开区间。

```text
片段 0：[0, end0)
片段 1：[end0 - overlap, end1)
片段 2：[end1 - overlap, end2)
```

Markdown 按文本段落处理，没有完整 Markdown AST、标题层级解析、表格或代码块保护。长表格、代码块和无空白字符串可能硬切；不能描述成模型驱动的语义切片。当前重叠也可能从句子中间开始。

偏移针对导入入口读取后的字符串，不是 UTF-8 字节位置。入口以 utf-8-sig 读取，支持 BOM；Python 文本读取会规范换行。来源哈希同样针对该字符串计算。空白片段可能跳过，非空白内容有覆盖测试。

## 3. 先离线预览

在仓库根目录执行，文件路径替换为自己准备的文本：

```powershell
python -m agent.retrieval.ingest docs/rag-evaluation-metrics-guide.md --source-id "guide/rag-metrics-v1" --title "RAG Metrics Guide" --category "documentation"
```

默认仅将预览 JSON 输出到终端，包含正文、稳定 ID、片段序号和偏移，不连接数据库、不调用模型。预览含完整源内容，应在本地查看；不要把客户文档预览提交到 Git 或公共日志。

自定义参数示例：

```powershell
python -m agent.retrieval.ingest docs/rag-evaluation-metrics-guide.md --source-id "guide/rag-metrics-v1" --title "RAG Metrics Guide" --chunk-size 1000 --overlap 100
```

参数改变会改变片段边界与 ID。当前 Reranker 正文预算为 2000 字符，建议候选 chunk_size 不超过该预算；标题也会消耗模型输入，字符数不能直接当成 token 预算。

## 4. 数据结构、引用与幂等

迁移新增两张表，不改写原始 001 迁移，不修改现有文章：

- `knowledge_sources`：逻辑来源 ID、原标题、类别、内容 SHA-256、算法版本、切片参数、模型和维度。
- `knowledge_chunk_provenance`：切片 UUID、来源 ID、片段序号、原文起止偏移。

切片本身仍存入 `knowledge_base`，因此当前 Vector 和 BM25 可以按原接口检索，Citation 的 document_id 仍引用实际返回记录。

切片 UUID 由来源、内容哈希、参数、模型和序号确定，同一输入生成相同 ID。检索标题包含片段序号和 UUID，控制在 VARCHAR(255) 以内；完整原标题保留在来源表。

当前来源元数据保存在数据库侧表中，**没有自动增加到前端 Citation 或 RetrievedDocument 的公开字段中**。管理员可以用引用中的 UUID 追溯：

```sql
SELECT s.source_id, s.title, s.content_sha256,
       p.chunk_index, p.start_offset, p.end_offset
FROM knowledge_chunk_provenance p
JOIN knowledge_sources s ON s.source_id = p.source_id
WHERE p.chunk_id = $1;
```

同一个 source_id 的内容和配置不变、切片数量完整时，重复入库不再追加记录；同 ID 内容或参数变化会报错，防止静默覆盖。相同来源如果改用另一个 source_id，会被当作另一份文档，因此 source_id 应由调用方稳定管理。不同版本共存需要显式决策，不建议直接给现有文章起新 ID 后重复导入线上库。

当前重复导入检查在持久化阶段，重复运行 live 命令仍会先请求 Embedding；数据库幂等不代表模型费用幂等。

## 5. 向量化契约

每片的 Embedding 输入是：

```text
原标题

片段正文
```

默认沿用当前查询检索器的 `text-embedding-v4`，显式请求 1536 维、float 编码。CLI 拒绝与当前默认检索模型冲突的 QWEN_EMBEDDING_MODEL 配置，以及非 1536 维配置。

每批最多 10 片；通过响应 index 将向量与输入重新对齐，不依赖响应数组顺序。校验数量、索引集合、维度和数值有限性。所有片段生成成功后，才在一个事务中写来源、知识条目和来源关联。任何模型批次失败都不会开始数据写入；SQL 中途失败会回滚该来源的全部写入。

客户端使用 30 秒请求超时并关闭自动重试，避免账户或模型配置错误时继续整批无效请求。已完成的模型请求仍可能计费，后续失败不会退回之前的费用。

模型和维度相同并不能自动证明远端已有库的语义空间一致；当前旧文章没有模型版本字段，部署前仍需确认原始向量来源。更换模型必须重建全库并更新查询配置，不能只修改导入参数。

## 6. 在隔离评测库中迁移和导入

先准备隔离的 PostgreSQL + pgvector 数据库，将该次进程的 DATABASE_URL 指向它。主机执行时使用可解析的主机地址；Compose 内部的 postgres 服务名通常不能直接用于 Windows 主机。

全新库先应用 001；已有 001 的库只应用 003，不重复执行初始建表脚本：

```powershell
# 仅用于全新数据库
python -m database.migrations.run_migration --migration 001_initial_schema.sql

# 新旧数据库均需新增这一步，可重复应用
python -m database.migrations.run_migration --migration 003_knowledge_chunk_provenance.sql
```

密钥通过服务端环境变量或根目录 .env 配置。预览确认后，以 `--execute-live` 显式启用真实模型调用和数据库写入：

```powershell
python -m agent.retrieval.ingest docs/rag-evaluation-metrics-guide.md --source-id "guide/rag-metrics-v1" --title "RAG Metrics Guide" --category "documentation" --execute-live
```

该命令会向已配置供应商发送原标题和片段正文。生产/客户资料入库前确认供应商与数据范围已获授权。不要提交 .env、生成向量、数据库备份或带客户正文的报告。

导入记录直接可被 Vector 查询；BM25 是进程内快照，需要重建或重启 API 才包含新片段。检索缓存当前使用 v1 key 和默认 3600 秒 TTL，导入 CLI 不负责清理缓存，也不会自动重启服务。

线上激活时应在维护窗口协调向量数据、BM25 快照和缓存。可以等待旧缓存过期，或对经确认的检索命名空间做定向失效；不能使用 FLUSHALL 清理整个 Redis。正式版本切换宜补充显式 corpus version，避免不同语料版本共享缓存。

## 7. 数据安全与回滚

结构迁移使用事务，仅创建侧表、约束和索引；不会删除、转换或回填现有文章。DDL 仍会获得数据库锁，生产迁移应安排维护窗口。没有新增数据库扩展，依赖已有 pgvector。

导入采用参数化 SQL、外键和唯一约束。需要为导入账号配置新表和 knowledge_base 的相应权限。来源 ID 发生冲突时禁止自动替换；暂不提供自动更新、删除、批量版本切换。

回滚分两种：

1. **仅执行了结构迁移**：旧代码不使用这两张新表，可以回退代码并保留空表；不必为回退立刻 DROP TABLE。
2. **已经写入切片**：先备份目标来源及其片段，核对 source_id 和受影响记录数，再在事务内删除该来源关联的 knowledge_base 行，外键会级联删除 provenance，最后删除来源行。原有无关联文章不在删除范围内。

以下为参数化回滚逻辑说明，需由维护程序绑定准确 source_id；本次测试没有在用户库执行：

```sql
BEGIN;
SELECT source_id FROM knowledge_sources WHERE source_id = $1 FOR UPDATE;
DELETE FROM knowledge_base
WHERE id IN (
  SELECT chunk_id FROM knowledge_chunk_provenance WHERE source_id = $1
);
DELETE FROM knowledge_sources WHERE source_id = $1;
COMMIT;
```

已发布的片段引用会受删除影响，应结合引用保留需求决定是否删除。删除后也必须刷新 BM25 与相关缓存。若既有文章被另一套迁移替换，需靠事前备份恢复；本导入器本身不替换旧文章。

## 8. 评测与上线门槛

切片不会自动保证召回更好。当前 1200/150 和原置信度阈值都不能宣称已完成长文档校准。

在相同模型、同一知识内容、同一查询集上比较“整篇”和“切片”两个隔离语料版本。标注每个问题真正需要的证据位置，再映射到新 chunk ID；原 Eval 通过标题匹配文档，不能直接把旧原标题标注用于带切片后缀的新文档，否则会报找不到标题。多个重叠片段包含同一证据时，明确采用片段级还是去重后的父文档级 Recall，避免重复计数造成指标失真。

至少记录：Recall@3、MRR、Precision@3、NDCG@3、无答案识别与误拒、重排降级和 P95，列出失败样本及重叠/边界原因。完整 Agent 链路另测 Grounded Answer Rate、Correct Escalation Rate 和路由正确率。

仅在 tuning 上选择切片参数和阈值，validation 检验，冻结 test 最终验收。近义问题和同一证据的变体应按组划分。未产生实际分数前，不宣称 Recall 提升，也不把旧 0.40/候选 0.43 原样认定为新阈值。

## 9. 验证方式与已知限制

```powershell
python -m pytest tests/test_retrieval/test_chunking.py tests/test_retrieval/test_ingest.py -q
```

数据库集成测试通过 CHUNK_TEST_DSN 指向空的临时数据库：

```powershell
python -m pytest tests/test_database/test_chunk_ingestion_integration.py -q
```

集成测试覆盖空库和有旧文章的上一版库，重复迁移、重复导入、变更拒绝、向量检索、引用 ID 追溯及中途写入失败回滚。测试将其 DDL 和数据包裹在事务中结束时回滚；不要将 CHUNK_TEST_DSN 指向正式业务库。

目前没有 PDF/DOCX 解析、语义分段模型、代码块保护、父文档合并返回、后台任务式增量更新、界面上传和自动索引发布。公开 API、Agent 审核逻辑和 Embedding 维度均未改变。
