# 首版需求追踪矩阵

本文将 PRD 的八个一级导航、全部 HTML 原型页面与现有接口/数据库设计及 OpenSpec 实施任务关联起来。API 路径以 `/api/v1` 为前缀。原型中的 JSON、统计数字、账号和成功状态均为演示内容，不表示页面已接通真实服务或数据。

## 页面与任务映射

| 一级模块 | PRD 章节 | HTML 原型 | 主要操作 | API 契约（已设计） | 主要实体 | OpenSpec 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 工作台 | 3.1–3.2 | [`index.html`](../html/index.html) | 查看指标、任务动态、提醒和最新文章；跳转待办；发起采集/创作/文章/上传/账号快捷操作 | `GET /dashboard`聚合概览/动态/待办/异常；具体动作调用业务模块；`GET /notifications`及本人偏好/已读接口 | `collection_runs`、`async_jobs`、`materials`、`creation_tasks`、`articles`、`publish_orders`、`notifications` | 1.1、1.7–1.8、8.1–8.4、8.7、8.10–8.11 |
| 采集管理 | 4.1–4.3 | [`collect.html`](../html/collect.html) | 管理来源和采集任务；配置关键词/范围/时间/调度/自动入库；立即执行；查看执行和结果；批量/单条入库、忽略、重试解析 | `/collection/sources`、`/collection/tasks`（含 `pause`/`resume`/`run`）、`/collection/runs`、`/collection/results`（含 `materialize`/`bulk-materialize`/`ignore`/`retry-parse`）；权限码 `collection:read`/`collection:write`/`collection:run`；契约见 [阶段 3](../development/api-phase-03.md) | `collection_sources`、`collection_tasks`、`collection_task_sources`、`collection_runs`、`collection_results`、`materials`、`material_revisions` | 1.1、3.1–3.2、3.4–3.7、3.9、3.11–3.12 |
| 智能创作 | 5.1–5.4 | [`create.html`](../html/create.html)、[`create-rule.html`](../html/create-rule.html)、[`create-material.html`](../html/create-material.html)、[`create-topic.html`](../html/create-topic.html) | 查看创作/规则/任务状态；创建和启停规则；配置触发、素材策略、筛选及模型；选素材或输入主题检索并确认候选；启动生成并查看结果/失败 | `/creation-rules`；`POST /creation-tasks`、`GET /creation-tasks/{id}`、`GET /creation-tasks/{id}/outputs`；主题预览使用 `POST /materials/search`；异步状态使用 `GET /async-jobs/{id}` | `creation_rules`、`creation_rule_collection_tasks`、`creation_tasks`、`creation_task_materials`、`creation_outputs`、`materials`、`material_revisions`、`async_jobs`、`model_configs` | 1.1、1.7–1.8、2.8、4.1–4.7、5.1–5.13 |
| 内容管理 | 6.1–6.3 | [`content.html`](../html/content.html)、[`editor.html`](../html/editor.html)、[`publish.html`](../html/publish.html) | 筛选文章/查看发布记录；编辑并保存新版本；AI 辅助和排版预览；查看引用；提交审核、通过/退回/驳回/复审；创建、确认、暂存、取消或重试发布并查结果 | `/articles`、`/articles/{id}`、`/articles/{id}/revisions`、`/articles/{id}/ai-actions`、`/articles/{id}/submit-review`、`/reviews/queue`、`/article-revisions/{revision_id}/reviews`、`/publish-orders` 及其 `confirm`、`cancel`、`attempts`、`retry` 子资源 | `articles`、`article_revisions`、`article_materials`、`reviews`、`publish_orders`、`publish_attempts`、`wechat_accounts`、`stored_objects` | 1.1、1.7–1.8、2.9、5.1–5.13、6.1–6.10、7.5–7.13 |
| 素材库 | 7.1–7.5 | [`library.html`](../html/library.html) | 搜索/筛选和查看素材、来源及引用；添加链接/上传/手工素材；分类标签；收藏、归档、批量处理；从素材进入创作 | `/materials`、`/materials/{id}`（含 `/revisions`、`/relations`、`/articles`、`/favorite`）、`/materials/favorites`、`/materials/bulk`、`/materials/categories`、`/materials/tags`、`/materials/search`（阶段 4）；文件授权、登记和下载接口；权限码 `material:read`/`material:write`/`material:search`；契约见 [阶段 3](../development/api-phase-03.md) | `materials`、`material_revisions`、`material_relations`、`material_categories`、`tags`、`material_tags`、`material_files`、`material_favorites`（按用户隔离）、`stored_objects` | 1.1、2.1–2.2、2.6、2.9、3.1、3.3、3.6–3.8、3.10–3.12、4.1–4.7、5.11 |
| 数据统计分析 | 8.1–8.2 | [`analytics.html`](../html/analytics.html) | 按日期、公众号、采集任务和数据类型筛选；查看采集/创作/审核/发布/账号指标；导出报表 | `GET /analytics/{kind}`及`GET /analytics/{kind}/export`，查询与导出共用明确口径/日期时区/支持维度 | `collection_runs`、`collection_results`、`materials`、`creation_tasks`、`articles`、`reviews`、`publish_orders`、`publish_attempts`、`account_article_metrics` | 1.1、8.1–8.4、8.8、8.10–8.11 |
| 账号管理 | 9.1–9.2 | [`accounts.html`](../html/accounts.html) | 授权/重授权、检测能力、配置默认账号和发布参数、解除绑定、同步素材及查看同步/发布记录 | `/wechat-accounts`、`/wechat-accounts/{id}`、`POST /wechat-accounts/authorization`、`GET /wechat-accounts/callback`、`POST /wechat-accounts/{id}/check`、`POST /wechat-accounts/{id}/sync`；解绑、默认配置、同步记录查询契约待补/核实 | `wechat_accounts`、`account_sync_runs`、`publish_orders`、`publish_attempts`、`stored_objects` | 1.1、2.6、7.1–7.4、7.10、7.12–7.13 |
| 系统设置 | 10.1–10.2 | [`settings.html`](../html/settings.html) | 编辑平台配置；管理模型并测试连接；用户/角色权限维护；查看接口/存储状态；配置通知；筛选操作日志 | `/settings/platform`、`/model-configs`、`/model-configs/{id}/test`、`/users`、`/roles`、`/roles/{id}/permissions`、`/notifications/preferences`、`/notifications`、`/settings/operation-logs`、`/settings/jobs`、`/settings/integrations`；用户PATCH/角色权限PUT/连接测试均已接入 | `system_settings`、`model_configs`、`users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`notification_preferences`、`notifications`、`operation_logs`、`async_jobs` | 1.1、1.4–1.6、2.7、5.4、5.9、8.1–8.2、8.5–8.6、8.9–8.11 |

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
| 登录会话/权限码/用户角色维护：阶段1基础已实现，阶段8补用户角色审计、无效角色拒绝、权限目录及完整页面 | 1.4–1.7、1.9；8.5、8.9–8.10 |
| 各页面分页、稳定排序、筛选字段、UTC 时间、统一错误码和成功/失败示例尚未固化为 OpenAPI | 1.5；各阶段接口任务；9.3 |
| 通知列表/已读/用户偏好/安全完整报表导出及工作台通知：阶段8已交付，见phase-08 | 8.1、8.2、8.4–8.6 |
| 账号解除绑定、默认账号/发布参数更新、同步运行历史的端点和微信真实授权方式/回调安全约束 | 7.1–7.4 |
| 素材收藏与批量逐项结果、分类/标签更新删除、有关联素材的删除/归档语义：接口契约（含 `BulkActionOut`/`BulkResultOut` 逐项结果、软删除 `references_preserved`、收藏幂等）已在任务 3.1 定义，见 [阶段 3 契约](../development/api-phase-03.md)；数据库约束与服务端强制待实现 | 3.1（契约已定义）、3.3、3.8 |
| 素材库按用户隔离收藏：接口契约（`PUT/DELETE /materials/{id}/favorite`、`GET /materials/favorites`）已在任务 3.1 定义，`material_favorites` 表（`(material_id, user_id)` 唯一）已在任务 3.3 建立；服务端接口实现在 3.8 | 3.1（契约已定义）、3.3（表已建）、3.8 |
| 异步任务取消/重试、创作结果列表、发布未知结果查询/人工核对、接口与存储服务连接测试的完整契约 | 2.2–2.5、5.1、5.7、7.5–7.9、8.5 |
| 原型展示的数字、账号、模型、来源、通知和成功状态为静态演示数据；需要以 API 聚合和真实权限替代，外部未接入时明确显示限制 | 1.7–1.10、各模块前端/验收任务、9.4、9.7–9.10 |
| PRD 所述约 29 个主要页面/操作状态是设计范围，不等于 29 个独立 HTML 文件；当前 13 个 HTML 原型均已在上表逐项归属 | 1.1；后续按对应模块任务验收 |

## 来源文件

阶段 7 的自有公众号直连接入、同步、规则目标账号和可控发布已完成 7.1–7.12 的内部实现与 fixture 验证；真实接入/账号实际权限验收仍在 7.13 阻塞。见 [阶段 7 记录](phase-07.md)，不能把模拟成功当作真实发布。

阶段 6 的内容列表、不可变编辑版本、排版预览、图片、审核队列与复审已经接入真实 API，任务 6.1–6.10 的测试与边界见 [阶段 6 验收](phase-06.md)。阶段7直连与发布的后续实施见上述记录。

采集增强 3.22–3.28 的 API、Worker、前端及复验证据见 [阶段 3 增强验收](phase-03-enhancement.md)。3.28 已补齐 DeepSeek 真实中文分析、用量与实际 Worker 闭环证据；旧阶段 3 的通过记录不替代本次增强验收。

- [产品需求文档](../instruction/PRD.md)
- [前端模块设计](../architecture/frontend-design.md)
- [API 设计](../architecture/api-design.md)
- [数据库设计](../architecture/database-design.md)
- [系统设计总览](../architecture/system-design.md)
- [本变更任务清单](../../openspec/changes/project-development-roadmap/tasks.md)

个人订阅号增量7.14–7.19：0020、wechat-draft-deliveries、DraftDeliveryPanel、wechat.draft与人工登记已接入；真实私有草稿写入/读回通过，官方API发布仍受限。证据及操作路径见 [阶段7增量验收](phase-07.md) 与 [真实草稿证据](wechat-draft-live-evidence.json)。


阶段8已完成，验收见 [阶段8记录](phase-08.md)。首版操作归属：工作台概览/最近文章/动态/待办/异常/快捷入口→8.1/8.3/8.7；采集/来源/任务趋势、素材新增/复用、创作/规则、人工审核、接口发布/草稿/人工登记→8.1/8.4/8.8；账号指标可用性和采集时间→8.2/8.4/8.8。日期/时区/账号/采集与创作任务/类型筛选及完整安全CSV导出→8.1/8.4/8.8/8.10。平台名称/介绍/标识/时区、模型/搜索配置及连接测试、用户角色/权限、微信管理入口、RustFS/向量环境摘要与连接检查→8.2/8.5/8.9。通知渠道/偏好/已读/隔离→8.2/8.6/8.9/8.10；操作人/模块/内容/时间/结果查询及跨用户异步监控→8.5/8.9/8.10。首版各操作均有任务归属；邮件/微信外发、个人号微信API发布、无权限运营指标及自主OCR等边界明确记录。

阶段9的实现、测试和外部能力边界见 [集成验收](phase-09.md) 与 [交付清单](release-checklist.md)。空库/历史迁移及约束核对→9.1；就绪/结构化日志/安全恢复面板→9.2；完整API字段/状态码/会话/权限/CSRF目录→9.3；生产构建导航/窄屏/刷新返回/权限变更/慢网恢复→9.4；采集到个人号草稿和模拟人工登记、素材复用和历史引用→9.5；Broker/Worker/模型/存储/未知草稿恢复→9.6（数据库中断待补）；50万素材/250万向量/30并发性能→9.7（执行中）；联合快照及恢复工具→9.8；正式runtime独立部署和运行/回退手册→9.9；最终交付清单→9.10（待收口）。真实API发布仍保持7.13未验收，个人号真实草稿证据单独保留。
