# 智媒助手 API 设计

## 1. 目的与边界

本文定义前端到 FastAPI 后端的首期 REST API。接口覆盖采集、素材、创作、文章审核发布、账号管理和系统设置。真实采集来源、模型服务与微信接口通过后端 adapter 调用，前端不直接访问这些服务。

## 2. 通用约定

- API 前缀：`/api/v1`；请求/响应为 JSON，字段使用 `snake_case`。
- 时间使用 ISO 8601 UTC；用户界面按 `Asia/Shanghai` 等用户时区显示。
- 列表请求统一支持 `page`、`page_size`、筛选字段和稳定排序；响应包含 `items`、`total`、`page`、`page_size`。
- 异步操作返回 HTTP `202`、`async_job_id` 和业务对象 ID；前端通过 `GET /async-jobs/{id}` 查询进度。
- 对运行采集、启动创作、确认发布、重试等有副作用的请求接受 `Idempotency-Key`。
- 错误格式统一包含稳定 `code`、可读 `message` 和可选 `field_errors`；不向客户端返回密钥、原始令牌或敏感堆栈。
- 所有业务 API 进行用户鉴权和权限检查；OAuth 回调和文件授权使用独立校验机制。

## 3. API 目录

### 3.1 登录、用户与权限

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/auth/login` | 登录并建立会话 |
| `POST` | `/auth/logout` | 注销会话 |
| `GET` | `/auth/me` | 当前用户与权限 |
| `GET/POST` | `/users` | 查询/创建用户 |
| `GET/PATCH` | `/users/{id}` | 用户详情/更新 |
| `GET/POST` | `/roles` | 查询/创建角色 |
| `PUT` | `/roles/{id}/permissions` | 替换角色权限集合 |

### 3.2 工作台与采集

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/dashboard/overview` | 核心指标 |
| `GET` | `/dashboard/activities` | 任务和文章动态 |
| `GET` | `/dashboard/alerts` | 失败、待审核和授权提醒 |
| `GET/POST` | `/collection/sources` | 来源列表（分页/关键词）/新增来源 |
| `GET/PATCH/DELETE` | `/collection/sources/{id}` | 详情/修改/停用或删除（保留历史追溯） |
| `POST` | `/collection/sources/{id}/test` | 测试来源连接（范围/重定向/超时/大小受限） |
| `GET/POST` | `/collection/tasks` | 查询（分页/状态）/创建采集任务 |
| `GET/PATCH/DELETE` | `/collection/tasks/{id}` | 详情/修改/删除（置 `archived`） |
| `POST` | `/collection/tasks/{id}/pause`、`/resume` | 暂停/恢复调度 |
| `POST` | `/collection/tasks/{id}/run` | 立即执行（202 受理） |
| `GET` | `/collection/runs`、`/runs/{id}` | 执行记录（按任务/触发/状态筛选）与详情 |
| `GET` | `/collection/results`、`/results/{id}` | 结果列表（按 run/解析/入库状态筛选）与详情 |
| `POST` | `/collection/results/{id}/materialize` | 单条结果入库为素材（202 异步） |
| `POST` | `/collection/results/bulk-materialize` | 批量入库，body 为 `result_ids`（≤100），返回逐项结果 |
| `POST` | `/collection/results/{id}/ignore` | 忽略结果（置 `ignored`） |
| `POST` | `/collection/results/{id}/retry-parse` | 重试正文解析（202 异步） |
| `GET` | `/collection/analysis`、`/analysis/{id}` | 分析结果列表与详情（含结构化建议与原文引用） |
| `POST` | `/collection/analysis/{id}/retry` | 重试分析（同一正文快照，不重新抓取） |
| `POST` | `/collection/analysis/{id}/apply` | 采用分析建议（`base_metadata_version` 冲突 409） |
| `POST` | `/collection/results/{id}/retain` | 人工保留为待筛选素材（填写原因） |

采集任务创建请求包含名称、采集模式、主题/关键词、来源 ID 或网站范围、时间范围、频率与时区、数量/分页限制、分析配置、自动入库、自动创作开关和启停状态。两种模式：`source`（默认，至少一个来源）与 `topic_search`（非空主题、可无来源、用 `allowed_domains` 限定网站；带 `source_ids` 为 422 模式冲突）。旧请求省略 `mode` 默认 `source`、省略 `analysis` 默认关闭；更新用 `CollectionTaskUpdateIn` 部分更新，省略字段保留原值。列表筛选支持状态、来源和时间；执行结果保留原文 URL、发布时间、采集时间、解析状态、去重候选和失败原因，运行计数区分 discovered/fetched/parsed/analyzed/materialized/filtered/review_required/failed。采集端点权限码：`collection:read`（查询）、`collection:write`（增删改/停用/忽略/重试/采用/保留）、`collection:run`（执行/入库）。批量入库返回 `BulkResultOut.items[]` 逐项状态与 `counts` 分类计数，批次不整体失败。详见 [阶段 3 接口契约](../development/api-phase-03.md)。

### 3.3 素材、文件和检索

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET/POST` | `/materials` | 查询（状态/分类/标签/关键词/我的收藏筛选）/手工新建素材 |
| `GET/PATCH/DELETE` | `/materials/{id}` | 素材详情、更新、软删除（引用保持可解析） |
| `GET` | `/materials/{id}/revisions` | 全部修订（`revision_no` 唯一递增） |
| `GET` | `/materials/{id}/relations` | 来源关联（采集结果/上传/链接等） |
| `GET` | `/materials/{id}/articles` | 被引用文章版本（含当时使用的修订） |
| `PUT/DELETE` | `/materials/{id}/favorite` | 收藏（同用户幂等）/取消收藏（按用户隔离） |
| `GET` | `/materials/favorites` | 我的收藏列表 |
| `POST` | `/materials/bulk` | 批量操作，返回逐项结果 |
| `GET/POST` | `/materials/categories`、`/categories/{id}` PATCH/DELETE | 分类树维护（父级不得成环） |
| `GET/POST` | `/materials/tags`、`/tags/{id}` PATCH/DELETE | 标签维护（删除仅解除关联） |
| `POST` | `/materials/search` | 关键词与向量混合检索预览（阶段 4） |
| `POST` | `/files/upload-grants` | 获取限定对象键、类型和大小的短时上传授权 |
| `POST` | `/files/upload-grants/{id}/complete` | 上传完成后校验并登记对象元数据 |
| `POST` | `/files/{object_id}/download-grant` | 获取受控短时下载授权 |

素材搜索请求字段：`query`、`scope`、`from`、`to`、`statuses`、`top_k`、`min_relevance`、`keyword_mode`。响应包含素材 ID、标题、匹配片段、相关度、来源和发布时间。创作接口必须提交最终选择的 `material_ids`，服务端持久化检索/采用关系。素材端点权限码：`material:read`（查询）、`material:write`（增删改/归档/批量/分类标签/收藏）。正文或标题变更创建新修订（不可变历史），状态/分类/标签原地变更；`DELETE` 为软删除。批量操作返回 `BulkActionOut.items[]` 逐项状态。详见 [阶段 3 接口契约](../development/api-phase-03.md)。

RustFS 凭据不暴露给浏览器；上传授权只允许访问特定对象键和有效期。完成回调应校验对象确实存在、大小和类型符合授权，再写入 `stored_objects`。

### 3.4 创作与 Agent

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET/POST` | `/creation-rules` | 查询/创建自动创作规则 |
| `GET/PATCH/DELETE` | `/creation-rules/{id}` | 查看、修改、停用规则 |
| `POST` | `/creation-tasks` | 创建素材、主题或人工触发的创作任务 |
| `GET` | `/creation-tasks/{id}` | 创作任务状态、进度和失败原因 |
| `GET` | `/creation-tasks/{id}/outputs` | 标题候选、大纲、摘要、关键词、封面建议等生成结果 |

主题检索应先调用 `/materials/search` 展示候选并允许人工调整，再创建 `mode=topic` 的任务。自动规则任务则服务端按规则检索素材，并记录触发来源、幂等键和未满足创作条件的原因。

创作规则字段包括名称、采集任务关联、目标公众号、主触发方式及参数、素材策略/筛选、最少素材数、相关度阈值、每篇引用数、每批篇数、文章类型、风格、字数范围、模型、提示词和启停状态。

### 3.5 文章、编辑与审核

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET/POST` | `/articles` | 文章列表/新建人工草稿 |
| `GET` | `/articles/{id}` | 文章详情与当前版本 |
| `POST` | `/articles/{id}/revisions` | 保存编辑内容并创建新版本 |
| `GET` | `/articles/{id}/revisions` | 版本历史 |
| `POST` | `/articles/{id}/ai-actions` | 润色、续写、改写、摘要或标题优化 |
| `POST` | `/articles/{id}/submit-review` | 提交当前版本审核 |
| `GET` | `/reviews/queue` | 待审核队列 |
| `POST` | `/article-revisions/{revision_id}/reviews` | 对指定版本提交审核结论 |

文章列表筛选支持状态、创作来源、公众号、创建时间和发布时间。文章版本字段包括标题、作者、关键词、摘要、Markdown 正文、封面对象和排版配置。AI 编辑接口返回建议结果，不直接覆盖已存版本；保存必须创建新 revision。

审核请求包含 `action`（`approve`/`return`/`reject`）、`checklist` 和 `comment`。退回/驳回需填写意见；通过动作只能作用于当前待审核版本。新版本提交后必须重新审核，旧版本审核记录保留但不能授权新版本发布。

### 3.6 账号、发布与统计

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/wechat-accounts`、`/wechat-accounts/{id}` | 账号列表/详情及权限摘要 |
| `POST` | `/wechat-accounts/authorization` | 发起 OAuth 授权 |
| `GET` | `/wechat-accounts/callback` | OAuth 回调，校验 state |
| `POST` | `/wechat-accounts/{id}/check` | 检查授权和接口权限 |
| `POST` | `/wechat-accounts/{id}/sync` | 启动素材同步 |
| `GET/POST` | `/publish-orders` | 查询/创建发布订单 |
| `GET` | `/publish-orders/{id}` | 订单状态和文章版本 |
| `POST` | `/publish-orders/{id}/confirm` | 运营确认后启动发布 |
| `POST` | `/publish-orders/{id}/cancel` | 取消未执行订单 |
| `GET` | `/publish-orders/{id}/attempts` | 历次接口调用结果 |
| `POST` | `/publish-orders/{id}/retry` | 新建一次发布尝试 |
| `GET` | `/analytics/{report}` | 采集、创作、审核、发布及账号指标报表 |

发布订单请求包含 `article_revision_id`、`account_id`、`mode`、可选 `scheduled_at` 和 `publish_note`。创建订单不等于确认发布；确认接口记录用户和确认时间。确认和执行时均校验版本审核结果及账号权限。每次重试新增 attempt，不覆盖之前错误。

账号指标必须标明采集时间和实际可用指标；无微信权限的数据返回不可用状态，不以 0 伪装。

### 3.7 设置与异步任务

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET/PUT` | `/settings/platform` | 平台信息、时区和通用任务配置 |
| `GET/POST` | `/model-configs` | 查询/新增模型配置（用途 analysis/generation/embedding） |
| `PATCH` | `/model-configs/{id}` | 修改模型配置 |
| `POST` | `/model-configs/{id}/test` | 测试模型连接 |
| `GET/POST` | `/search-configs` | 查询/新增搜索配置（独立于采集来源与 embedding） |
| `POST` | `/search-configs/{id}/test` | 测试搜索服务连接 |
| `GET/PUT` | `/settings/notifications` | 通知类型与渠道配置 |
| `GET` | `/operation-logs` | 按用户、模块、结果和时间筛选操作日志 |
| `GET` | `/async-jobs/{id}` | 查询异步任务状态、进度和错误摘要 |

模型密钥通过 `credential_ref` 管理；查询响应只返回是否已配置等安全摘要。异步任务 ID 使用统一 UUID，领域记录另提供各自详情接口，不使用含义不明的 `/tasks/{id}`。

## 4. 状态与权限规则

- 采集、创作、解析、embedding、同步和发布等耗时动作返回 `async_job_id`；领域执行记录拥有业务状态，异步任务记录拥有 Worker 运行状态。
- 创建任务、提交审核、确认发布和重试必须服务端校验前置状态，不能仅依赖前端按钮是否可点击。
- 发布订单只能绑定审核通过的具体文章版本；文章修改后创建新版本，新版本审核通过前不能发布。
- 采集和创作任务按业务幂等键防重；发布订单和每次调用 attempt 分开，防止网络重试重复发布或丢失失败历史。
- API 按角色和操作权限鉴权，操作日志需记录操作者及结果并对敏感字段脱敏。

## 5. 主要端到端流程

### 采集入库

```text
POST /collection/tasks/{id}/run
→ 创建 collection_run + async_job + outbox_event
→ Celery Worker 执行来源发现 / 主题搜索，保存候选
→ 抓取、正文提取、时间与关键词筛选，保存 collection_results
→ 完全重复匹配 → 可选 LLM 分析与新进展比较
→ 满足条件自动入库 / 等待人工筛选
→ 创建 material/material_revision
→ 异步生成 material_chunks embedding
→ 发送一次素材就绪事件，阶段 5 检查规则后创建 creation_task
```

### 主题/素材创作

```text
POST /materials/search → 前端展示候选并允许勾选
→ POST /creation-tasks（mode、topic、material_ids、配置）
→ 服务端持久化任务和素材关系并投递 Celery
→ Worker 调用 LangGraph 检查条件、分析素材、生成文章
→ 保存 creation_outputs、article、article_revision
→ 文章进入待审核
```

### 审核发布

```text
保存新 article_revision → submit-review
→ reviewer 对 revision 提交 approve/return/reject 和检查项
→ 通过后创建 publish_order（指定 revision/account/time）
→ 运营显式 confirm
→ Worker 执行前再次校验审核版本与账号权限
→ 每次微信调用写 publish_attempt
→ 更新订单和文章状态，失败可创建新 attempt 重试
```

## 6. 采集增强契约（待实现，任务 3.14–3.25）

本节为现有 `/collection/*` 契约的增量设计，不表示 OpenAPI 已生成或接口已实现。运行行为及默认预算见 [采集增强设计](collection-design.md)。原阶段 3 实现记录保留在 [api-phase-03.md](../development/api-phase-03.md)，新能力实现后另附验收。

### 6.1 创建与更新兼容

`POST /collection/tasks` 保留现有字段，增加下列字段；PATCH 省略的字段保留现有值，显式清空必须通过对应模式校验。

| 字段 | 默认与规则 |
| --- | --- |
| `mode` | `source`；另支持 `topic_search` |
| `source_ids` | source 模式至少一个；topic_search 可省略/空，非空返回 422，网站范围使用 allowed_domains |
| `topic` | 主题搜索必填非空；指定来源可选，供相关性分析使用 |
| `search_config_id` | 主题搜索必填且配置启用；source 不调用搜索服务 |
| `allowed_domains` | 默认空；主机及其子域限制，后端再次校验结果和重定向；source 可作为额外限制 |
| `max_articles`、`max_pages_per_source` | 默认 20、5；分别 1–100、1–20；运行总预算由管理员配置限制 |
| `analysis_enabled`、`analysis_model_config_id` | 默认 false；开启时必须指定可用 analysis 配置 |
| `analysis_apply_policy` | `suggest_only` 默认；另支持 `fill_empty`，只能填充空且无人维护的字段 |

来源接口的 `web_page` 增加 `page_kind=article/list`（默认 article），list 必须提交文章链接和下一页规则；RSS 使用条目发现。`keywords` 为空不做短语筛选，非空在两模式均匹配标题/正文任一短语；主题模式同时用于固定搜索词。`time_range_days` 沿用既有字段，运行保存冻结窗口。

### 6.2 配置与安全选项

| 端点 | 权限与用途 |
| --- | --- |
| `GET/POST /search-configs`、`GET/PATCH /search-configs/{id}` | settings:read/write；管理搜索提供方、能力、版本、限额、启停及凭据引用 |
| `POST /search-configs/{id}/test` | settings:write；有限连接测试，审计实际外部调用，凭据错误与无结果区分 |
| `GET/POST /model-configs`、`GET/PATCH /model-configs/{id}`、`POST /model-configs/{id}/test` | 原规划端点提前实现，读为 settings:read，写/测试为 settings:write；用途 analysis/generation/embedding |
| `GET /collection/config-options` | collection:read；仅返回可选搜索及 analysis 模型的 ID、名称、用途、可用性和限额摘要，不泄露 endpoint/credential_ref |
| `GET /materials/analysis-options` | material:read；仅返回素材分析可选模型的同类安全摘要 |

配置更新增加版本；查询不回显明文密钥，凭据通过只写输入或受控引用提供。现有 settings 权限复用，不为普通编辑开放配置管理。选项可用性不替代执行前权限、配置与预算复验。

### 6.3 阶段记录和分析操作

| 端点 | 契约与权限 |
| --- | --- |
| `GET /collection/runs/{id}/candidates` | collection:read；分页候选、发现来源/查询、URL、搜索摘要、筛选原因、阶段状态及关联 result_id |
| `GET /collection/runs/{id}/stages` | collection:read；阶段/attempt、计数、错误、预算、起止时间、当前 async_job_id |
| `POST /collection/runs/{id}/retry` | collection:run；202，仅恢复原运行失败且允许重试的步骤；请求指定 stage（discovery/fetch/parse/analysis），复用已完成快照与原预算 |
| `POST /collection/results/{id}/analyze` | collection:write；202，按保存正文和任务分析配置创建或复用分析；新配置显式提交，原失败重试也复用正文 |
| `POST /materials/{id}/analyze` | material:write；202，提交 material_revision_id、model_config_id 及可选主题/关键词，绑定明确修订 |
| `GET /collection/results/{id}/analyses`、`GET /materials/{id}/analyses` | 分别 collection:read/material:read；分页返回分析及 attempts、版本、输入依据、是否过期，不回显凭据 |
| `POST /materials/{id}/analyses/{analysis_id}/apply` | material:write；选择采用字段/确认新标签分类，提交 base_revision_id、base_metadata_version；409 表示正文/人工字段冲突 |
| `POST /collection/results/{id}/review` | collection:run；记录人工筛选动作和原因；支持保留待筛选、确认可用、确认重复及确认新进展；关联目标素材/修订需校验存在及权限，创建新分类标签另需 material:write |

所有副作用接受 `Idempotency-Key`；同键同内容返回原受理结果，同键异内容 409。review 若需要入库返回 202，并复用现有入库服务；仅记录决定可返回 200。候选无可读正文只能忽略/重试，不能确认可用。失败分析可以人工保留为 pending_review，不能通过“保留”动作伪造成功；确认可用须显式复核筛选原因并记录人工覆盖依据。

原 materialize/bulk-materialize 端点继续可用，但必须执行增强后的时间/分析/判重前置条件；未满足返回逐项稳定原因（如 `analysis_required`、`review_required`），不能成为绕过新规则的入口。人工已入库素材确认可用沿用素材状态更新端点，增加 `reason`、`base_revision_id` 和 `base_metadata_version`，对存在就绪阻塞的对象执行同样的显式复核，不允许普通状态 PATCH 静默绕过。

### 6.4 响应与状态

- 保留 result 的现有解析/入库状态，新增 `analysis_status`、`decision_status`、原因、正文快照/hash、分析 ID 和 ready 状态；decision 区分 eligible/excluded/needs_review/duplicate/new_progress。查询包含 summary 时标明 source/analysis/manual 的来源。
- 分析结果包含 purpose（single_material/dedup_compare）、模型和提示词版本、任务输入指纹、原文快照/素材修订、summary、category/tag 建议、relevance/reason、facts（提取事实+原文引用），比较结果另含目标修订和新增事实依据；基于当前版本返回 `stale` 标识。summary/schema 不合法的记录不返回为成功建议。
- 阶段状态和计数区分搜索空结果、技术失败、筛选排除、待人工和预算耗尽；旧任务 analysis_status 为 skipped，而非 succeeded。瞬时网络失败可重试，非法模型输出/配置需修正后人工重试，预算用尽不能通过普通 retry 重置；新运行才重新分配预算。
- 保留 401/403/409/422 契约；无分析配置/模式冲突在提交时校验，运行时外部错误写阶段记录。兼容字段与 OpenAPI/前端类型在 3.14 固化，实际接入证据在 3.28 记录。

### 3.22–3.27 已实现的增量接口

| 接口 | 行为及权限 |
| --- | --- |
| GET /collection/config-options | collection:read；返回启用的来源/搜索/analysis 模型 ID 和名称，不返回凭据引用 |
| GET /collection/runs/{id}/candidates | collection:read；候选、搜索摘要/排名、阶段 attempt 和正文快照/hash/提取器版本 |
| POST /collection/runs/{id}/retry | collection:run + CSRF；202；复用成功阶段，取消/非失败运行返回 409，原预算不重置 |
| GET /collection/analysis、/{id} | collection:read；分析/比较用途、输入快照/hash、模型/提示词版本、目标修订和动态 stale |
| POST /collection/analysis/{id}/retry | collection:run + CSRF；202；从保存正文恢复，生成 async_job 与 outbox，不重新搜索抓取 |
| POST /collection/analysis/{id}/apply | collection:write + CSRF；提交 base_metadata_version、apply 和已确认分类/标签；过期、归档及版本冲突 409，未知对象需确认 422 |
| POST /collection/results/{id}/retain | collection:write + CSRF；reason 必填，保留待筛选并写审计，不生成就绪事件 |
| POST /materials/{id}/analysis | material:write + CSRF；202；model_config_id、可选 topic/keywords，绑定当前不可变修订 |
| GET/PATCH /model-configs/{id} | settings:read/write；变更增加 config_version，省略凭据引用时保留原配置；响应只给 credential_configured |

MaterialOut/MaterialDetailOut 增加 summary、metadata_version；素材更新可提交 base_metadata_version。人工编辑递增版本并记录字段来源，异步 fill_empty 不覆盖人工维护字段。实现、真实连接限制及复验见 [阶段 3 增强验收](../development/phase-03-enhancement.md)。

