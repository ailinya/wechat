# 首版需求追踪矩阵

本文将 PRD 的八个一级导航、全部 HTML 原型页面与现有接口/数据库设计及 OpenSpec 实施任务关联起来。API 路径以 `/api/v1` 为前缀。原型中的 JSON、统计数字、账号和成功状态均为演示内容，不表示页面已接通真实服务或数据。

## 页面与任务映射

| 一级模块 | PRD 章节 | HTML 原型 | 主要操作 | API 契约（已设计） | 主要实体 | OpenSpec 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 工作台 | 3.1–3.2 | [`index.html`](../html/index.html) | 查看指标、任务动态、提醒和最新文章；跳转待办；发起采集/创作/文章/上传/账号快捷操作 | `GET /dashboard/overview`、`GET /dashboard/activities`、`GET /dashboard/alerts`；具体动作调用对应模块接口；通知读取 API 待补 | `collection_runs`、`async_jobs`、`materials`、`creation_tasks`、`articles`、`publish_orders`、`notifications` | 1.1、1.7–1.8、8.1–8.4、8.7、8.10–8.11 |
| 采集管理 | 4.1–4.3 | [`collect.html`](../html/collect.html) | 管理来源和采集任务；配置关键词/范围/时间/调度/自动入库；立即执行；查看执行和结果；批量/单条入库、忽略、重试解析 | `/collection/sources`、`/collection/tasks`（含 `pause`/`resume`/`run`）、`/collection/runs`、`/collection/results`（含 `materialize`/`bulk-materialize`/`ignore`/`retry-parse`）；权限码 `collection:read`/`collection:write`/`collection:run`；契约见 [阶段 3](../development/api-phase-03.md) | `collection_sources`、`collection_tasks`、`collection_task_sources`、`collection_runs`、`collection_results`、`materials`、`material_revisions` | 1.1、3.1–3.2、3.4–3.7、3.9、3.11–3.12 |
| 智能创作 | 5.1–5.4 | [`create.html`](../html/create.html)、[`create-rule.html`](../html/create-rule.html)、[`create-material.html`](../html/create-material.html)、[`create-topic.html`](../html/create-topic.html) | 查看创作/规则/任务状态；创建和启停规则；配置触发、素材策略、筛选及模型；选素材或输入主题检索并确认候选；启动生成并查看结果/失败 | `/creation-rules`；`POST /creation-tasks`、`GET /creation-tasks/{id}`、`GET /creation-tasks/{id}/outputs`；主题预览使用 `POST /materials/search`；异步状态使用 `GET /async-jobs/{id}` | `creation_rules`、`creation_rule_collection_tasks`、`creation_tasks`、`creation_task_materials`、`creation_outputs`、`materials`、`material_revisions`、`async_jobs`、`model_configs` | 1.1、1.7–1.8、2.8、4.1–4.7、5.1–5.13 |
| 内容管理 | 6.1–6.3 | [`content.html`](../html/content.html)、[`editor.html`](../html/editor.html)、[`publish.html`](../html/publish.html) | 筛选文章/查看发布记录；编辑并保存新版本；AI 辅助和排版预览；查看引用；提交审核、通过/退回/驳回/复审；创建、确认、暂存、取消或重试发布并查结果 | `/articles`、`/articles/{id}`、`/articles/{id}/revisions`、`/articles/{id}/ai-actions`、`/articles/{id}/submit-review`、`/reviews/queue`、`/article-revisions/{revision_id}/reviews`、`/publish-orders` 及其 `confirm`、`cancel`、`attempts`、`retry` 子资源 | `articles`、`article_revisions`、`article_materials`、`reviews`、`publish_orders`、`publish_attempts`、`wechat_accounts`、`stored_objects` | 1.1、1.7–1.8、2.9、5.1–5.13、6.1–6.10、7.5–7.13 |
| 素材库 | 7.1–7.5 | [`library.html`](../html/library.html) | 搜索/筛选和查看素材、来源及引用；添加链接/上传/手工素材；分类标签；收藏、归档、批量处理；从素材进入创作 | `/materials`、`/materials/{id}`（含 `/revisions`、`/relations`、`/articles`、`/favorite`）、`/materials/favorites`、`/materials/bulk`、`/materials/categories`、`/materials/tags`、`/materials/search`（阶段 4）；文件授权、登记和下载接口；权限码 `material:read`/`material:write`/`material:search`；契约见 [阶段 3](../development/api-phase-03.md) | `materials`、`material_revisions`、`material_relations`、`material_categories`、`tags`、`material_tags`、`material_files`、`material_favorites`（按用户隔离）、`stored_objects` | 1.1、2.1–2.2、2.6、2.9、3.1、3.3、3.6–3.8、3.10–3.12、4.1–4.7、5.11 |
| 数据统计分析 | 8.1–8.2 | [`analytics.html`](../html/analytics.html) | 按日期、公众号、采集任务和数据类型筛选；查看采集/创作/审核/发布/账号指标；导出报表 | `GET /analytics/{report}`；按筛选导出的契约需补充/确认 | `collection_runs`、`collection_results`、`materials`、`creation_tasks`、`articles`、`reviews`、`publish_orders`、`publish_attempts`、`account_article_metrics` | 1.1、8.1–8.4、8.8、8.10–8.11 |
| 账号管理 | 9.1–9.2 | [`accounts.html`](../html/accounts.html) | 授权/重授权、检测能力、配置默认账号和发布参数、解除绑定、同步素材及查看同步/发布记录 | `/wechat-accounts`、`/wechat-accounts/{id}`、`POST /wechat-accounts/authorization`、`GET /wechat-accounts/callback`、`POST /wechat-accounts/{id}/check`、`POST /wechat-accounts/{id}/sync`；解绑、默认配置、同步记录查询契约待补/核实 | `wechat_accounts`、`account_sync_runs`、`publish_orders`、`publish_attempts`、`stored_objects` | 1.1、2.6、7.1–7.4、7.10、7.12–7.13 |
| 系统设置 | 10.1–10.2 | [`settings.html`](../html/settings.html) | 编辑平台配置；管理模型并测试连接；用户/角色权限维护；查看接口/存储状态；配置通知；筛选操作日志 | `/settings/platform`、`/model-configs`、`/model-configs/{id}/test`、`/users`、`/roles`、`/roles/{id}/permissions`、`/settings/notifications`、`/operation-logs`；用户角色更新、接口配置/连接测试、通知查询和异步监控契约待补/确认 | `system_settings`、`model_configs`、`users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`notification_preferences`、`notifications`、`operation_logs`、`async_jobs` | 1.1、1.4–1.6、2.7、5.4、5.9、8.1–8.2、8.5–8.6、8.9–8.11 |

## 缺口与待确认项

### 采集增强映射（新增设计，尚未实施）

原表描述基础页面和任务；下表追加本次增强，不将原任务完成记录扩展为新能力已完成。行为依据为 PRD 4.4/7.5、[采集增强设计](../architecture/collection-design.md)与当前 change 的 `collection-management/material-analysis/material-library/platform-management` 规格。现有 HTML 没有这些新控件，后续在既有页面扩展，不新增一级导航。

| 模块/操作 | API 或服务边界 | 数据 | 新任务 |
| --- | --- | --- | --- |
| 采集：主题搜索/指定来源、可选网站、限额和分析设置 | `/collection/tasks` 增量字段；`/collection/config-options`；搜索/来源发现 adapter | tasks、search_configs、候选/发现依据 | 3.13–3.18、3.24 |
| 采集：RSS 多文章、栏目分页、正文/日期及关键词筛选 | 发现→抓取→正文服务；`/collection/runs/{id}/candidates` | collection_candidates/discoveries/content_snapshots | 3.18–3.19、3.22、3.25 |
| 采集：阶段计数/错误/预算、失败单步重试 | `/collection/runs/{id}/stages`、`/retry` | stage_attempts、run 配置快照/预算 | 3.14–3.15、3.22、3.25–3.28 |
| 素材：LLM 摘要/分类/事实建议与新进展依据 | results/materials 的 analyze、analyses 查询 | material_analysis_runs/attempts、输入修订和事实引用 | 3.16、3.20–3.21、3.23、3.25 |
| 素材：人工采用、保留待筛选、确认可用、元数据冲突 | analysis apply、result review、受约束素材状态更新 | metadata_version/字段来源、review_decisions、ready outbox | 3.21–3.23、3.25–3.28 |
| 系统设置：搜索/模型最小配置、连接测试、用途与预算 | `/search-configs`、提前的 `/model-configs` | search_configs、model_configs 及配置版本 | 3.13–3.17、3.24；5.4/5.9 复用、8.5/8.9 完善 |
| 创作：消费就绪事件、复用当前分析但仍检查条件 | 既有规则/创作服务，非互联网搜索 | material.ready 事件、creation_tasks 与素材修订关联 | 3.22、5.1–5.6 |
| 验收：新旧任务、权限、迁移、幂等与中文来源证据 | 实际集成实例 + 确定性提供方 fixture + 真实连通 | 独立增强验收及工具评估记录 | 3.13、3.26–3.28 |

### 基础能力与证据核实

以下为当前 PRD、原型与架构/API 设计对照后尚需落地或核实的事项。任务编号表示计划处理位置，不表示已实现；个别行已注明“契约已定义”，表示接口层（任务 3.1）就绪、数据库/实现仍待后续任务。

原表中的阶段 3 开发状态需结合当前代码和 `phase-03.md` 阅读，不把历史“待实现”文字当最新进度。对旧验收要求与证据不一致的部分，本次独立记录于 [采集增强前缺口](collection-enhancement-gaps.md)：关键词/日期未执行、RSS 无条目发现、URL/hash 不能证明事件新进展，以及 DB/跨组件验证被跳过；3.26/3.28 负责复验，原勾选记录不被静默改写。

| 缺口或待确认项 | 处理任务 |
| --- | --- |
| 登录会话、权限码、用户/角色维护的完整请求字段和响应错误契约；当前 API 目录未覆盖全部用户角色操作 | 1.4–1.7、1.9；8.5、8.9–8.10 |
| 各页面分页、稳定排序、筛选字段、UTC 时间、统一错误码和成功/失败示例尚未固化为 OpenAPI | 1.5；各阶段接口任务；9.3 |
| 通知列表/已读状态、用户级偏好、报表导出契约；工作台未读提醒 API | 8.1、8.2、8.4–8.6 |
| 账号解除绑定、默认账号/发布参数更新、同步运行历史的端点和微信真实授权方式/回调安全约束 | 7.1–7.4 |
| 素材收藏与批量逐项结果、分类/标签更新删除、有关联素材的删除/归档语义：接口契约（含 `BulkActionOut`/`BulkResultOut` 逐项结果、软删除 `references_preserved`、收藏幂等）已在任务 3.1 定义，见 [阶段 3 契约](../development/api-phase-03.md)；数据库约束与服务端强制待实现 | 3.1（契约已定义）、3.3、3.8 |
| 素材库按用户隔离收藏：接口契约（`PUT/DELETE /materials/{id}/favorite`、`GET /materials/favorites`）已在任务 3.1 定义，`material_favorites` 表（`(material_id, user_id)` 唯一）已在任务 3.3 建立；服务端接口实现在 3.8 | 3.1（契约已定义）、3.3（表已建）、3.8 |
| 异步任务取消/重试、创作结果列表、发布未知结果查询/人工核对、接口与存储服务连接测试的完整契约 | 2.2–2.5、5.1、5.7、7.5–7.9、8.5 |
| 原型展示的数字、账号、模型、来源、通知和成功状态为静态演示数据；需要以 API 聚合和真实权限替代，外部未接入时明确显示限制 | 1.7–1.10、各模块前端/验收任务、9.4、9.7–9.10 |
| PRD 所述约 29 个主要页面/操作状态是设计范围，不等于 29 个独立 HTML 文件；当前 13 个 HTML 原型均已在上表逐项归属 | 1.1；后续按对应模块任务验收 |

## 来源文件

采集增强 3.22–3.28 的 API、Worker、前端及复验证据见 [阶段 3 增强验收](phase-03-enhancement.md)。3.28 已补齐 DeepSeek 真实中文分析、用量与实际 Worker 闭环证据；旧阶段 3 的通过记录不替代本次增强验收。

- [产品需求文档](../instruction/PRD.md)
- [前端模块设计](../architecture/frontend-design.md)
- [API 设计](../architecture/api-design.md)
- [数据库设计](../architecture/database-design.md)
- [系统设计总览](../architecture/system-design.md)
- [本变更任务清单](../../openspec/changes/project-development-roadmap/tasks.md)
