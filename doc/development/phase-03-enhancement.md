# 阶段 3 采集增强实施与验收记录

日期：2026-11-18。范围：OpenSpec project-development-roadmap 3.22–3.28。

## 状态

3.22–3.28 已完成。固定采集流程、分析管理 API、采集与设置前端通过确定性服务/浏览器验证；补充 DeepSeek 真实中文分析与实际 Celery Worker 闭环证据。真实样例结果及质量边界见下文，fixture 不替代真实提供方验收。

## 实现

- 任务创建/编辑保存采集模式、主题、网站范围、数量/分页和分析配置；运行接受时冻结任务及来源快照。
- Worker 使用 engine handler，网络调用位于写事务之外。每个候选保存 fetch/parse/analyze/materialize 尝试；来源发现保存独立状态和有限重试次数。
- 已成功阶段与来源恢复时复用；运行租约控制并发执行。取消与业务副作用在事务边界复验；每次运行有固定时间与调用预算。
- RSS/栏目发现、主题搜索、正文提取、时间与关键词筛选、可选分析及证据比较接入同一固定流程。未知日期/不确定建议待人工筛选，失败不冒充完整成功。
- 内容键事务锁和既有逻辑键防止重复素材及模型分析；material_ready_events 唯一键与 outbox 在同一事务写入，不创建创作任务。
- material.ready 事件保留在 outbox；尚未配置阶段 5 消费任务的事件不进入当前 Celery dispatcher，避免投递到不存在的消费者。事件不等于人工审核或发布确认。
- 查询分析历史、原文事实引用与 stale 状态；失败分析从快照重试；独立素材分析绑定修订。采用建议提交页面读取的元数据版本，冲突 409；fill_empty 尊重人工维护来源，未知分类/标签只能人工选择已存在对象。
- 人工保留结果写入原因审计，保留为 pending_review，不伪造分析成功、不产生就绪事件。
- 前端保留八个一级模块，采集页增加模式/来源配置、任务编辑、候选与阶段恢复、分析历史及人工采用。系统设置提供最小模型/搜索配置与连接测试。素材详情可刷新恢复修订与分析记录；窄屏导航与表格滚动已检查。

## 验证证据

- 阶段 3 扩大回归：137 项通过、0 跳过，使用实际 PostgreSQL wetchat_test 与 Redis 第 15 号测试库；含旧来源/素材/调度契约与数据库行为、跨来源并发去重、模型 fixture、分析管理与 Broker 投递/中断。
- 后续增补验证：旧结构 0004 → head、0010 → head 的迁移回退/重升保留历史原文；正文修改后历史分析 stale；未知分类/标签不自动创建；人工清空摘要后 fill_empty 不覆盖。
- 浏览器固定响应测试：主题模式不填来源可提交、刷新恢复结果筛选、分析失败重试、无设置权限拒绝；桌面与 390px 窄屏截图在 test-results/。
- 浏览器真实 API/DB 闭环：tests/e2e/collection-live.spec.ts 经实际 FastAPI、会话权限、任务 CRUD、生产 Worker handler、数据库与素材/分析 API 完成主题 → 素材；搜索/HTTP/模型外部服务使用显式 fixture。
- 后端默认测试的 skipped 项不计入数据库验收。完整跨阶段测试尝试因旧 RustFS 测试等待停止，不宣称整个项目或存储全链路通过。
- 前端生产构建、36 项组件测试及 3 项浏览器测试通过；后端默认运行 173 passed / 127 skipped，跳过项不计入数据库验收。凭据与模型/搜索专项回归 47 项通过。OpenSpec 严格校验单独执行。lint 存在 React hooks 等 warning，不等同于构建失败。

## 真实连接证据

2026-11-18 07:53 UTC，运行 backend/scripts/verify_collection_connections.py：

| 项目 | 实际结果 |
| --- | --- |
| Tavily 查询“人工智能 最新进展” | 请求成功，返回 1 个候选，2655ms；提供方报告 credits=1 |
| 首条候选正文抓取 | cn.weforum.org 返回 HTTP 403，明确记录为站点访问限制；未用搜索摘要替代正文 |
| 固定中文官方样例 off-1 | cac.gov.cn 返回 HTTP 200，Trafilatura 2.3.1 提取 1583 字 Markdown 与正确中文标题；未识别到明确发布时间，按未知日期待筛选 |
| analysis 模型（08:47 UTC 补验） | DeepSeek deepseek-chat，两例中文结构化分析成功；真实用量与引用见下文 |

此前中文来源样例逐条结果和正式选型限制见 collection-tool-evaluation.md 与 collection-samples.json。单次搜索连通不代表任意来源可抓取，也不代表模型质量通过。

### DeepSeek 真实分析与 Worker 闭环

配置名称为“DeepSeek 素材分析”，用途 analysis，协议 openai-compatible，接口 `https://api.deepseek.com/v1/chat/completions`，模型 `deepseek-chat`，凭据引用 `DEEPSEEK_API_KEY`。数据库仅保存引用；API 与 Worker 优先读取进程环境，缺失时只读取根目录 `.env` 的指定凭据，不向全局环境注入数据库等其他配置。连接测试提示明确要求 JSON；401/403 归类鉴权失败且不重试。

真实调用证据见 [模型结果](analysis-model-live-evidence.json)（2026-11-18 08:47 UTC）：

| 样例 | 输入 | 延迟 | token 用量 | 结果 |
| --- | --- | --- | --- | --- |
| 固定中文合成样例 | 65 字，非真实报道 | 1703ms | 输入 253 / 输出 236 / 合计 489 | 中文摘要、分类/标签建议、相关性理由、4 条原文事实引用 |
| 中文官方文章 off-1 | 实际 HTTP 200，提取正文 1583 字 | 3297ms | 输入 1107 / 输出 627 / 合计 1734 | 中文摘要、分类/标签建议、相关性理由、8 条原文事实引用 |

两例均通过结构校验与引用原文定位。定位仅证明引文存在，不证明陈述被引文完整支持，也不是外部事实核验；官方样例中存在概括多个因素却只引用首项的情况，仍需人工核对。未知分类/标签不自动创建，建议由人工决定是否采用。官方样例未提取到发布时间，仍按未知日期待筛选。

[真实 Worker 证据](analysis-worker-live-evidence.json)（08:53 UTC）记录实际 API → outbox → Redis → Celery Worker → DeepSeek → PostgreSQL：连接测试 687ms，作业及分析均 succeeded，无错误，用量输入 260 / 输出 201 / 合计 461 token。素材明确标为测试样例、非真实报道，保留为手动素材，未创建创作或发布任务。此闭环未使用外部模型 fixture。

## 迁移与运行

新增迁移：0011_collection_pipeline 增加运行租约、发现完成标记、候选到结果映射及阶段 attempt 唯一索引；0012_discovery_recovery 保存来源发现状态。此前 0009/0010 修复 scope 长度并保存分析输入与模型版本。

1. 停止 Worker/Beat/dispatcher 后备份 PostgreSQL。业务库需先备份并核对 DATABASE_URL，再在 backend 下运行 uv run alembic upgrade head。本轮只自动迁移 wetchat_test。
2. 按既有 phase-02 说明启动 API、Celery Worker、Beat 与 dispatcher。采集仍使用 collection.run 和 outbox；Windows Worker 使用 solo pool。建议 JOB_SOFT_TIME_LIMIT_SECONDS 至少 660，以覆盖 600 秒业务预算与保存终态时间；原默认值 300 会更早结束作业。
3. 暂停任务不会补跑历史运行。运行配置快照不随任务编辑而改变；超过原运行预算应新建运行，不能借重试扩大原预算。
4. 失败阶段可在候选/运行页恢复；分析可独立重试而不抓取。单独分析成功后，可恢复执行推进后续入库阶段。取消的运行不可按普通失败恢复。
5. 回退必须停掉正在执行的作业。0011/0012 的回退删除新增执行映射和来源恢复状态，应优先应用前向修复；历史素材修订和原文保留。0009 向下收窄 scope 时如已有 collection_result 分析会显式拒绝，不能截断数据。

## 复验入口

- 单元测试：backend 下 uv run pytest -q。
- 数据库/Redis：在当前进程设置独立 TEST_DATABASE_URL 和 REDIS_URL（本轮为 Redis /15），执行 tests/test_collection*.py、tests/test_material*.py 与本轮分析/发现/来源/搜索/正文/Broker 集成测试。PowerShell 原生命令不展开文件通配符，需通过 Get-ChildItem 展开测试文件列表。
- 前端：frontend 下 pnpm test、pnpm build。
- 浏览器：根目录 pnpm exec playwright test tests/e2e/collection.spec.ts。真实 API fixture 闭环需单独启动 backend/tests/collection_e2e_app.py，并设置 COLLECTION_E2E_FIXTURE=1、DATABASE_URL 指向 /wetchat_test、APP_SECRET_KEY、E2E_SEARCH_KEY；测试进程设置 E2E_BACKEND_URL。该 fixture 模块严格拒绝其他数据库，不能作为业务部署入口。
- 真实连接：backend 下运行 uv run python scripts/verify_collection_connections.py；调用计入提供方配额，脚本不输出凭据。
- 真实模型：backend 下运行 uv run python scripts/verify_analysis_model.py（可加 --probe 仅测连接）；实际 Worker 闭环使用 scripts/verify_analysis_worker.py，需先启动隔离预览 API/Worker/Beat。调用计入提供方配额，完整运行保存脱敏 JSON 证据。

## 3.28 验收结论

本轮本地预览：http://127.0.0.1:5175，API 8013，实际 Worker/Beat 已启动，使用 wetchat_test 与 Redis /15。测试账号 admin / correct-password；“DeepSeek 素材分析”已启用，搜索凭据引用为 TAVILY_API_KEY。业务数据库未迁移，预览数据属于隔离测试数据。

确定性回归覆盖预算、异常、幂等与恢复，真实连接补齐搜索、中文来源及模型输出/用量和 Worker 链路，3.28 完成。保留站点 403、动态网页、未知日期和模型引文语义覆盖等已知边界；不据有限样例宣称任意网站可采集或模型输出无需人工审核。
