# 阶段 5：智能创作验收

日期：2026-11-19。变更 `project-development-roadmap` 的 5.1–5.13。

规则支持人工、定时、采集完成和素材就绪数量触发，以及仅新增、新增加历史未使用、全库三种素材策略。全库有主题时复用混合检索，向量服务不可用会记录关键词降级；结果最多取检索前 100 项的语义分数，其他候选按关键词评分。任务保存条件检查、候选与最终采用的素材修订；产物按槽位幂等保存，重试保留已完成文章，重新生成关联原任务。创作页面支持素材或主题提交、规则维护、任务和输出查看。文章详情可追溯引用素材的历史正文及来源。

## 验证

- 独立 PostgreSQL/pgvector 测试库：创作 schema、模型和集成测试共 14 项通过，覆盖四触发、三策略、六类条件、旧分析、并发窗口、批次恢复、取消、重新生成、恶意正文指令和历史引用。生成流程没有审核或发布工具，文章状态为待审核。
- 前端生产构建和组件测试通过；规则编辑、素材选择、任务原因和文章链接由组件测试覆盖。更新后的阶段 4 Playwright 用例尚未在本次执行。
- [脱敏真实模型证据](creation-live-evidence.json)：根目录 `.env` 中的 `qwen4-max` 与 `qwen3.7-text-embedding-flash`（1024 维）处理合成测试素材，向量化和混合检索成功，生成带引用的待审核草稿，耗时 17.43 秒。该验证调用真实模型及生产 handler，通过测试客户端与独立数据库运行，直接领取并执行 handler；本次没有通过 Redis/Celery 进程或浏览器复验该闭环。一次样例不能代表输出质量或生产性能。

## 运行与复现

升级前备份并确认数据库目标，在 backend 目录执行 `uv run alembic upgrade head`；运行 API、Celery Worker、Beat 和 outbox dispatcher。Windows 本地 Worker 使用 `--pool solo`。Beat 每分钟调度创作规则及消费素材就绪事件；outbox 分派创作和向量作业。设置页需要启用 generation 用途的模型配置，规则或手动请求选择该配置。文本模型读取 `MODEL_NAME`、`OPENAI_BASE_URL`、`OPENAI_API_KEY`；向量读取 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_DIMENSION` 和 `OPENAI_API_KEY`；同名进程环境变量优先于根目录 `.env`。向量维度当前为 1024，切换向量模型后应为素材当前修订重建向量。

确定性测试需要专用测试数据库，设置 `TEST_DATABASE_URL` 后在 backend 执行 `python -m pytest tests/test_creation_schema.py tests/test_creation_model.py tests/test_creation_integration.py -q`。真实模型复现还需设置 `CREATION_LIVE_TEST=1`，执行 `python -m pytest tests/test_creation_live.py -q`；该测试会重置 `TEST_DATABASE_URL` 指向的数据库并消耗模型配额，只能指向隔离测试库。可将 `CREATION_LIVE_EVIDENCE` 设置为输出文件路径保存脱敏证据。

## Agent 边界

LangGraph 顺序执行素材输入检查、引用已有分析事实、生成与输出校验。素材正文作为不可信数据，模型无工具调用、审核或发布权限；引用必须属于本次选中的素材修订。模型请求在文章写入事务外执行；写入前检查作业仍处于执行中并锁定任务。已完成槽位持久化，失败或取消后的重试不会重复创建这些文章；未完成槽位会重新执行生成流程。生成草稿及封面文字建议均需人工审核。
