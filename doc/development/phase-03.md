# 阶段 3 验收记录（2026-11-18）

对应任务：tasks.md 第 3 组（3.1–3.12）。接口契约语义见 [api-phase-03.md](api-phase-03.md)，
需求映射见 [追踪矩阵](traceability.md)。本阶段完成「采集 → 素材」闭环。

## 实现范围

| 任务 | 产物 |
| --- | --- |
| 3.1 | 采集/素材 schemas、状态词表、停用/删除语义、逐项批量结果、分类标签与收藏契约（OpenAPI） |
| 3.2 | 迁移 `0003_collection`：来源/任务/来源关联/运行/结果表，时区与去重领取字段、状态 CHECK、窗口唯一索引、暂停调度触发器 |
| 3.3 | 迁移 `0004_materials`：素材/修订/分类/标签/文件关联/素材关系/用户收藏表，修订唯一、复合外键约束当前修订归属 |
| 3.4 | 来源管理 + 首个 HTTP 来源 adapter（SSRF 防护、逐跳重定向复检、超时/大小限制）、连接测试 |
| 3.5 | 任务 CRUD/立即执行/暂停恢复、Beat 调度、事务创建 run+job+outbox、worker handler |
| 3.6 | HTML/DOCX/PDF → Markdown 解析服务，保留原文/原链接/失败原因 |
| 3.7 | 重复判定、新进展 `update_of`、单条/批量/自动入库、忽略、解析重试 |
| 3.8 | 手工/链接/上传素材、不可变修订、分类树防环、标签、用户隔离收藏、归档与软删除 |
| 3.9 | 采集前端（任务/来源/执行/结果、立即执行、批量入库、结果跳真实素材） |
| 3.10 | 素材库前端（列表/详情、手工/链接/文件创建、分类标签、收藏、归档、批量、引用空态） |
| 3.11 | 跨组件集成测试（重复/并发入库、新进展、解析重试、跨用户收藏、受约束删除、链路对账） |

## 验证证据

| 验证项 | 结果 | 证据 |
| --- | --- | --- |
| 契约与 OpenAPI | 通过 | `test_collection_materials_contract.py`：`/collection/*`、`/materials/*` 路径注册、批量示例符合 schema、软删除 `references_preserved`、202 受理示例；`GET /materials/favorites` 命中专用 handler 而非参数路由 |
| 迁移结构 | 通过（本地） | `0003`/`0004` Alembic 链 `0001→0002→0003→0004` 校验；DDL-shape 测试覆盖 5+8 张表、状态 CHECK、修订唯一、复合外键、批量防重、删除保留策略、触发器/函数与回退 |
| 来源 adapter | 通过（fixture） | 14 项单测：拒绝内网/保留地址与凭据 URL、白名单、重定向逐跳复检、重定向上限、响应大小、超时透传；中文/失败 fixture 可复现，传输与 DNS 可注入 |
| 调度窗口 | 通过（本地） | `test_collection_schedule.py`：manual 不调度、hourly/daily/weekly 时区窗口、cron 匹配/不匹配、未知时区回退 UTC |
| 解析服务 | 通过（fixture） | 9 项测试：中文 HTML（标题/加粗/链接/列表、跳过样式）、DOCX（标题样式/段落）、PDF（UTF-16 中文）、纯文本；不支持/损坏/空文档返回稳定 `ParseError.code` |
| 入库判定 | 通过（本地） | `test_materialization.py`：完全重复关联旧素材且不建新修订、新进展建 `update_of` 且旧正文不变、重复提交幂等、忽略冲突、批量逐项计数 |
| 素材库逻辑 | 通过（本地） | `test_material_service.py`：正文变更建新修订、仅状态变更不建修订、分类循环 409、收藏按 user_id 隔离、软删除守卫 |
| 前端 | 通过 | 类型检查 `tsc -b` 通过；`pnpm test` **35 passed**（采集页 5 + 素材库页 5 + 既有 25），覆盖 URL 状态恢复、立即执行反馈、结果跳真实素材、中文正文可见、引用空态、错误不伪造成功 |
| 后端 | 通过（本地可运行集） | `86 passed`（含契约、DDL-shape、调度、解析、入库判定、素材库逻辑单测）；DB 行为/跨组件集成测试在设置 `TEST_DATABASE_URL` 后执行 |

## 端到端演示（采集 → 素材）

拾取一个来源（fixture 或真实）后的链路（3.12 要求）：

1. 创建来源（保存前校验 URL 范围）→ 创建任务（绑定来源、调度方式）→ 立即执行
   （202 受理，同事务写 `collection_run`+`async_job`+`outbox_event`）。
2. Worker `collection.run` 抓取来源 → 按内容类型解析为 Markdown → 写 `collection_results`
   （保留原文 `raw_content` 与原链接 `url`，解析失败记录 `parse_status`/`error`）。
3. 单条/批量入库：完全重复关联既有素材（`duplicate`）、同来源新内容建新素材并写
   `update_of`（`new_progress`）、否则新建（`materialized`）；`auto_materialize` 任务自动入库。
4. 结果页「查看素材」跳转到真实素材详情，显示当前修订中文正文与来源。

## 来源能力与正文转换限制

- **来源 adapter**：当前仅 HTTP(S) `rss`/`web_page`，限制协议、主机（拒绝内网/保留地址）、
  重定向（逐跳复检、上限 2）、超时（10s）、响应大小（2 MiB）。真实站点的反爬/鉴权未接入，
  以 fixture 验证可重复行为；真实来源需配置后另行连通性验证。
- **正文解析**：HTML 用标准库解析（跳过 script/style，保留标题/段落/列表/链接）；DOCX 读取
  段落、标题样式与表格；PDF 解压 FlateDecode 流并按文本操作符提取，**对扫描件/加密/复杂 CID
  字体可能无可读文本**，返回 `no_extractable_text`。不支持类型/损坏文件返回明确错误码。
  原始文件仍存 RustFS、原链接存 `collection_results.url`，失败原因可见且可重试。

## 阻塞与未验收项（如实披露）

1. **真实外部服务**：本环境无 PostgreSQL/Redis/RustFS 实例与 Docker，DB 行为与跨组件集成测试
   （`test_collection_schema.py`、`test_material_schema.py`、`test_collection_tasks.py`、
   `test_materialization_integration.py`、`test_material_library.py`、`test_collection_integration.py`）
   在 `TEST_DATABASE_URL` 未设置时**按约定跳过**；fixture 与单测通过不等于真实数据库验收。
   设置测试库后可完整执行，预期覆盖迁移升级/回退、约束强制与链路对账。
2. **真实采集来源**：fixture 证明 adapter 行为，但未对真实站点做连通性验收；不把模拟采集标为真实完成。
3. **文件下载授权**：附件下载沿用阶段 2 的 RustFS 短期授权（任务 2.6/2.9），阶段 3 素材详情可
   查看文件标识，真实下载需在 RustFS 实例上验证。
4. **文章引用空态**：`GET /materials/{id}/articles` 在任务 5.3 建立 `article_materials` 后返回真实数据，
   当前前端显示明确空态（不伪造引用）。

## 交付说明

- 阶段 3 的 12 项任务已全部勾选；契约、数据库、后端、前端、测试与验收记录齐备。
- 本记录区分「本地/fixture 通过」与「真实外部服务未验收」；后续阶段依赖本阶段契约稳定。
