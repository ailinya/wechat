# 阶段 4：素材分块与检索验收

日期：2026-11-19。范围：`project-development-roadmap` 4.1–4.7。

素材修订产生时，事务内写入异步向量任务及 outbox；Worker 对正文确定性分块，按修订、模型配置和配置版本记录构建结果。失败保留错误码，重试复用已完成分块。搜索只使用当前修订和当前环境配置下成功完成的向量；关键词可独立工作，混合检索的向量服务失败时返回明确降级状态。主题页支持候选勾选、移除和补选已使用素材；创作提交将在阶段 5 接入。

## 验证

- 独立 PostgreSQL 16 / pgvector 测试库：45 项后端测试通过，覆盖分块、维度、失败重试、修订隔离、检索、权限与素材采集回归。
- 前端生产构建通过；素材页及主题候选组件测试 6 项通过，验证全库、降级提示、刷新保留与移除。
- Playwright 1 项通过：浏览器登录后经真实 FastAPI 和独立测试库，使用实际向量模型搜索并补选已使用素材，刷新后移除。素材为合成固定样例。
- 重建命令在独立测试库以 3 条素材试运行并执行，3 条均复用已有成功任务，未产生重复任务。
- 真实向量模型采用根目录 `.env` 的 `qwen3.7-text-embedding-flash`，维度 1024。3 条素材、4 条中文查询中，3 条相关查询预期候选均排首位；无关查询在阈值 0.75 下为空。单次混合查询 248–286 ms，包含外部服务调用；结果与修订见 [实测证据](material-search-live-evidence.json)，样例定义见 [评估集](material-search-evaluation.md)。

规模只有 3 条素材，该时延不能推断大规模生产性能。现阶段使用精确向量距离，全库关键词在应用端计算；上线前应以实际数据量和并发测量，再决定是否增加近似索引及关键词索引。

## 配置与重建

文本调用从根目录 `.env` 读取 `MODEL_NAME`、`OPENAI_BASE_URL` 和 `OPENAI_API_KEY`；向量调用读取 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_DIMENSION`、`EMBEDDING_BATCH_SIZE` 和 `OPENAI_API_KEY`。同名进程环境变量优先；密钥不要写入版本库。向量基址支持 Qwen 原生 API 与 `compatible-mode/v1`。数据库须升级到 `0014_material_embedding_runs`，启动 API、Celery Worker 和 outbox dispatcher。

模型或服务地址变化后，新素材自动使用新配置，已有素材需要为当前修订重建。先在 backend 目录激活虚拟环境并确保 `DATABASE_URL` 指向目标库，然后执行：

```powershell
$env:PYTHONPATH='.'
python scripts/rebuild_material_embeddings.py
python scripts/rebuild_material_embeddings.py --apply
```

第一条仅显示候选数量；第二条逐素材提交任务。重复执行复用同修订、同配置的成功或进行中任务；已失败任务会重新入队。可在任务 API 查询失败原因，也可通过 `POST /materials/{material_id}/embedding-rebuild` 重试单条。重建期间旧模型向量保留用于追溯，不参与新模型空间的搜索；已归档素材不入队。模型构建完成前可使用关键词检索。

当前数据库列、配置校验和服务固定为 1024 维。更换到不同维度前，必须先设计并执行新的数据库迁移、更新代码维度校验及接口契约，并对现有素材完成新模型重建；仅修改 `.env` 的维度不能完成切换，也不能混用不同维度或模型的向量。
