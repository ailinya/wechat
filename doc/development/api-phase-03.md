# 阶段 3 接口契约：采集与素材（任务 3.1）

本文保留原阶段 3 实现语义。新增 3.13–3.28 的两种采集模式、搜索及 LLM 分析尚未实现，未来契约见 [API 增量设计](../architecture/api-design.md)，行为见 [采集增强设计](../architecture/collection-design.md)。原实现的关键词/时间过滤、RSS 条目发现和新进展判定差距见 [缺口记录](collection-enhancement-gaps.md)；本文的旧规则不能作为增强验收标准。

机器可读契约以 `/openapi.json` 为准（tags: `collection`、`materials`）；本文记录稳定语义决策。
来源端点已在任务 3.4 实现；任务 CRUD/暂停恢复/立即执行及运行查询已在任务 3.5 实现；
结果查询、单条/批量入库、忽略、重试解析已在任务 3.7 实现；素材库端点已在任务 3.8 实现。
阶段 3 全部端点均已落地，不再有 501 契约桩。501 与真实失败区分的机制保留供后续阶段使用。

## 权限码

沿用 `PermissionCode`（`backend/app/schemas/auth.py`），本阶段端点使用：

| 权限码 | 适用范围 |
| --- | --- |
| `collection:read` | 来源/任务/运行/结果查询 |
| `collection:write` | 来源与任务增删改、停用、忽略、重试解析 |
| `collection:run` | 立即执行、单条/批量入库（有副作用） |
| `material:read` | 素材/修订/关系/引用/分类/标签/收藏查询 |
| `material:write` | 素材增删改、归档、批量操作、分类/标签维护、收藏 |

## 采集（/api/v1/collection）

| 端点 | 语义 |
| --- | --- |
| `GET/POST /collection/sources` | 来源分页列表（关键词筛选、稳定排序）/ 新建来源（幂等）；**已实现 3.4** |
| `GET/PATCH/DELETE /collection/sources/{id}` | 详情 / 改名、启停、改地址 / 停用或删除，保留既有运行与结果追溯；**已实现 3.4** |
| `POST /collection/sources/{id}/test` | 连接测试；范围、重定向、超时、响应大小受限，失败返回可读 error；**已实现 3.4** |
| `GET/POST /collection/tasks` | 任务分页列表（按状态筛选）/ 新建任务；**已实现 3.5** |
| `GET/PATCH/DELETE /collection/tasks/{id}` | 详情 / 关键词、来源、调度、开关更新 / 置 `archived`，历史运行与来源关联保留；**已实现 3.5** |
| `POST /collection/tasks/{id}/pause`、`/resume` | 暂停后不再调度，历史保留；恢复调度；**已实现 3.5** |
| `POST /collection/tasks/{id}/run` | 立即执行：返回 **202** `AsyncJobAccepted`，重复请求按幂等键冲突（409）；**已实现 3.5** |
| `GET /collection/runs`、`/runs/{id}` | 执行记录分页（按任务/触发/状态筛选）与详情；**已实现 3.5** |
| `GET /collection/results`、`/results/{id}` | 采集结果分页（按 run/解析/入库状态筛选）与详情（原文 URL、来源）；**已实现 3.7** |
| `POST /collection/results/{id}/materialize` | 单条入库（异步，202）；重复提交幂等返回原关联，不重复建素材；**已实现 3.7** |
| `POST /collection/results/bulk-materialize` | 批量入库，body 为 `result_ids`（≤100），返回逐项结果；**已实现 3.7** |
| `POST /collection/results/{id}/ignore` | 结果置 `ignored`，不建素材；**已实现 3.7** |
| `POST /collection/results/{id}/retry-parse` | 解析重试（异步，202）；**已实现 3.7** |

状态词表（见 `backend/app/schemas/collection.py`）：来源 `active/inactive/unavailable`；任务
`active/paused/archived`（`archived` 即删除，运行与来源链接保留）；运行
`pending/running/succeeded/partial/failed`；结果解析 `pending/parsed/failed`；结果入库
`pending/materialized/duplicate/new_progress/ignored/failed`。

## 素材（/api/v1/materials）

| 端点 | 语义 |
| --- | --- |
| `GET/POST /materials` | 素材分页（状态/分类/标签/关键词/我的收藏筛选）/ 手工新建（首修订，修订号 1）；**已实现 3.8** |
| `POST /materials/from-link` | 从网页链接抓取并解析正文创建素材；**已实现 3.8** |
| `POST /materials/from-upload` | 从已登记上传对象（服务端解析 PDF/DOCX/文本）创建素材；**已实现 3.8** |
| `GET /materials/favorites` | 我的收藏列表（按用户隔离）；**已实现 3.8** |
| `POST /materials/bulk` | 批量操作（归档/取消归档/标记使用/设置分类/增删标签），返回逐项结果 |
| `GET/POST /materials/categories`、`/categories/{id}` PATCH/DELETE | 分类树维护；父级不得成环（409）；非空分类删除冲突（409 `category_not_empty`） |
| `GET/POST /materials/tags`、`/tags/{id}` PATCH/DELETE | 标签维护；重名 409；删除仅解除关联，素材保留 |
| `GET/PATCH/DELETE /materials/{id}` | 详情（当前修订正文 + 收藏状态）/ 更新（正文/标题变更创建新修订）/ 软删除；**已实现 3.8** |
| `GET /materials/{id}/revisions` | 全部修订，`revision_no` 唯一递增 |
| `GET /materials/{id}/relations` | 来源关联（采集结果/上传/链接等） |
| `GET /materials/{id}/articles` | 引用该素材的文章版本（阶段 5 建表后返回真实数据，当前为空态） |
| `PUT /materials/{id}/favorite` | 收藏（同用户重复收藏幂等返回原记录） |
| `DELETE /materials/{id}/favorite` | 取消收藏（204，他人收藏不受影响） |

状态迁移（任务 3.8 服务端强制）：`pending_review → ready_to_use | archived`；
`ready_to_use → used | partially_used | archived`；`used/partially_used → ready_to_use | archived`；
`archived → ready_to_use`。`duplicate` 由去重流程赋值，不由用户设置。

正文/标题变更创建新修订（不可变历史）；状态/分类/标签原地变更。
`DELETE /materials/{id}` 为软删除（`archived` + 删除标记），已有引用（文章版本/采集结果/来源）
保持可解析；收藏按用户隔离。

## 批量逐项语义

- `BulkResultOut`（采集批量入库）：`items[]` 每项 `{result_id, status, material_id?, error?}`，
  `counts` 按 `materialized/duplicate/new_progress/ignored/failed` 计数。批次不整体失败。
- `BulkActionOut`（素材批量）：`items[]` 每项 `{material_id, status=success|skipped|failed, error?}`。

## 幂等与异步

- 有副作用的采集端点接受 `Idempotency-Key`（≤128）；作用域固定，持久化唯一约束
  `(scope, user_id, key)`；同键同内容返回原结果，同键异内容 409 `idempotency_conflict`。
- 立即执行、单条/批量入库、解析重试返回 **202** `AsyncJobAccepted`
  `{async_job_id, resource_type, resource_id, status="accepted"}`；业务状态与 Worker 运行态分离。
- 立即执行/定时调度在同一事务创建 `collection_run` + `async_job` + `outbox_event`；定时窗口键由
  任务时区计算（hourly/daily/weekly/cron），`(task_id, window_key)` 唯一索引防重。Beat 每 60 秒
  调用 `schedule_collection_runs`，暂停任务的 `scheduled` run 同时被查询条件与数据库触发器阻止。
  Worker handler（`collection.run`）抓取来源并写入 `collection_results`（入库在 3.7）。
- 正文解析服务（`app/services/document_parser.py`，任务 3.6）支持中文 HTML、DOCX 与 PDF 转 Markdown：
  HTML 用 `html.parser` 提取标题/段落/标题层级/列表/链接并跳过脚本样式；DOCX 用 `zipfile`+XML
  读取段落、标题样式与表格；PDF 解压 FlateDecode 流并按文本操作符提取（含 UTF-16 中文）。
  不支持或损坏的文件返回稳定 `ParseError.code`（`unsupported_type`/`docx_parse_failed`/
  `pdf_parse_failed`/`no_extractable_text`/`empty_document`），handler 将其记录到
  `collection_results.parse_status` 与 `error`；原始响应存 `raw_content`、原链接存 `url`，均不丢失。

## 入库判定（任务 3.7）

- 完全重复：同一 `dedup_key` 且正文 hash 与既有素材当前修订一致 → 结果关联到既有素材，
  `materialize_status='duplicate'`，不创建新修订/素材。
- 新进展：同一来源但正文 hash 不同 → 创建新素材与首修订，`materialize_status='new_progress'`，
  并写入 `material_relations(source=新, target=旧, relation_type='update_of')`；旧正文不变。
- 重复提交同一结果（已处于终态且有 `material_id`）直接返回原关联；批量入库允许逐项成功/失败，
  `counts` 按状态计数；`auto_materialize` 任务在采集 handler 完成后自动入库其 parsed+pending 结果。

## 实现说明

- 来源 adapter（`app/adapters/source_fetch.py`）限制协议/主机、重定向逐跳复检、超时与响应大小；
  内网/保留地址及非白名单主机在保存前即被拒绝。传输与 DNS 解析可注入，fixture 无需联网。
- `NotImplementedError` 由统一错误处理转为 **501 `not_implemented`**（与阶段 2 一致）。
- 实际路径采用集合式 `/collection/{resources}` 命名；`doc/architecture/api-design.md` 的
  `/collection-sources` 等为早期规划写法，以本节与 `/openapi.json` 为准。
- 前端类型由 `backend/scripts/generate_api_types.py` 从 OpenAPI 重新生成。
