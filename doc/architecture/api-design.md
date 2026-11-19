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

阶段 9 的完整实现目录、权限、CSRF 和状态码以自动生成的 [API 权限矩阵](api-permissions.md) 及 [字段契约快照](api-catalog.json) 为准。以下分领域说明保留业务语义；服务路由与 OpenAPI 的方法/路径集合由导出脚本逐项核对。

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
| `GET` | `/dashboard` | 按当前权限返回核心指标、动态、待办和异常；前三个拆分路径未提供 |
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
| `POST` | `/materials/{id}/embedding-rebuild` | 锁定一个素材修订并异步重建向量 |
| `GET/POST` | `/materials/categories`、`/categories/{id}` PATCH/DELETE | 分类树维护（父级不得成环） |
| `GET/POST` | `/materials/tags`、`/tags/{id}` PATCH/DELETE | 标签维护（删除仅解除关联） |
| `POST` | `/materials/search` | 关键词与向量混合检索预览（阶段 4） |
| `POST` | `/files/upload-grants` | 获取限定对象键、类型和大小的短时上传授权 |
| `POST` | `/files/upload-grants/{id}/complete` | 上传完成后校验并登记对象元数据 |
| `POST` | `/files/{object_id}/download-grant` | 获取受控短时下载授权 |

`POST /materials/search` 请求字段：

| 字段 | 类型/约束 | 说明 |
| --- | --- | --- |
| `query` | string, 1–500 chars | 用户主题或关键词；空白归一化后不得为空 |
| `scope` | `current` / `all` | 默认 `current`；`all` 可包含已使用素材，但不包含已归档/软删除素材 |
| `from`, `to` | RFC 3339 timestamp, optional | 按素材来源发布时间筛选；未知时间不满足显式时间边界 |
| `statuses` | material status[], optional | 与 `scope` 及权限过滤取交集 |
| `top_k` | integer, 1–100; default 20 | 返回上限 |
| `min_relevance` | number, 0–1; optional | 对最终混合相关度分数过滤 |
| `keyword_mode` | `hybrid` / `keyword_only` | 默认 `hybrid`；请求 `hybrid` 时语义服务失败按下述降级契约处理 |

关键词检索先对正文和查询执行 Unicode NFKC、大小写折叠及空白/标点归一化；中文连续字符生成重叠二元组，拉丁字母与数字按词项匹配。关键词分数为命中查询词项权重占比，范围 `[0,1]`。语义分数使用余弦相似度 `c` 映射为 `V=clamp((c+1)/2, 0, 1)`；关键词分数为 `L`，混合分数为 `R=w*L+(1-w)*V`，`w` 默认 `0.5`，后续可由检索配置固定。三者都不是概率或事实可信度。按 `R` 降序、素材 ID 升序稳定排序；`min_relevance` 比较 `R`。关键词单路时 `R=L`，响应仍标明模式。当前向量配置来自根目录 `.env`：`EMBEDDING_MODEL=qwen3.7-text-embedding-flash`、`EMBEDDING_DIMENSION=1024`，凭据引用 `OPENAI_API_KEY`；API key 不得进入请求日志、证据或 API 响应。文本模型同样从 `MODEL_NAME`、`OPENAI_BASE_URL` 和 `OPENAI_API_KEY` 读取。

响应 `items[]` 含 `material_id`、`title`、`matched_revision_id`、`snippet`、`source`（来源类型、来源标题、规范化 URL 或附件标识）、`published_at`、`keyword_score`、`semantic_score`（降级时为 null）、`relevance_score`、`score_explanation` 和 `usage_status`；顶层含 `mode`、`degraded`、`degradation_reason`。无论 `scope` 为何，只允许素材当前有效正文修订参与默认检索；历史修订只用于明确的历史追溯，不可提升为当前命中。无匹配返回空 `items`，不合成结果。

当 `keyword_mode=hybrid` 的 embedding 配置缺失、禁用、超时或返回维度不符时，返回可识别的 `keyword_only` 降级结果（`degraded=true`，给出稳定错误码/原因）；若关键词检索也不可用则返回标准错误，不得把服务故障伪装成零结果。明确请求 `keyword_only` 时不调用 embedding 服务。

向量重建使用 `POST /materials/{material_id}/embedding-rebuild`，可选 `revision_id`；省略时锁定请求受理时的当前修订。接受后返回 `202`、`async_job_id`、`resource_id` 与目标 `revision_id`。重复请求按素材、修订、embedding 配置版本幂等；调用者通过 `/async-jobs/{id}` 查询进度。只允许设置权限发起；新修订产生后，旧修订的重建任务不得写成当前修订结果。失败保留可查询原因，可对同一修订显式重试；不删除其他模型版本或历史修订向量。

创作接口必须提交最终选择的 `material_ids`，服务端持久化检索/采用关系。素材端点权限码：`material:read`（查询）、`material:write`（增删改/归档/批量/分类标签/收藏）、`material:search`（检索）、`settings:write`（重建向量）。正文或标题变更创建新修订（不可变历史），状态/分类/标签原地变更；`DELETE` 为软删除。批量操作返回 `BulkActionOut.items[]` 逐项状态。详见 [阶段 3 接口契约](../development/api-phase-03.md)。

RustFS 凭据不暴露给浏览器；上传授权只允许访问特定对象键和有效期。完成回调应校验对象确实存在、大小和类型符合授权，再写入 `stored_objects`。

### 3.4 创作与 Agent

阶段 5 创作契约：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `GET/POST` | `/creation-rules` | 分页查询、创建规则；规则字段由 `RuleIn` 定义，目标账号接入阶段 7 前必须为空 |
| `GET/PATCH/DELETE` | `/creation-rules/{id}` | 规则详情、修改及停用；需保留已有任务快照 |
| `POST` | `/creation-rules/{id}/run` | 人工触发自动规则；触发窗口和请求幂等键防止重复批次 |
| `GET/POST` | `/creation-tasks` | 查询创作记录；素材/主题请求必须提交最终素材及对应修订，主题模式还须提交主题 |
| `GET` | `/creation-tasks/{id}` | 查询触发来源、窗口、决策、执行状态、候选和实际采用记录 |
| `GET` | `/creation-tasks/{id}/outputs` | 查询批次槽位、文章及版本、完整生成结果和实际素材引用 |
| `POST` | `/creation-tasks/{id}/cancel` | 取消待执行或执行中任务，不覆盖已完成产物 |
| `POST` | `/creation-tasks/{id}/retry` | 重试失败任务的未完成槽位；保留已完成文章 |
| `POST` | `/creation-tasks/{id}/regenerate` | 创建关联原任务的新任务，不改写历史结果 |

自动模式只从规则触发，素材由服务端选择；手动模式提交 `materials: [{material_id, revision_id}]` 并在受理时校验该修订仍为当前版本，避免检索后悄然替换输入。请求 `mode` 为 `material` 或 `topic`；前者和后者都不得提交空素材，后者的 `topic` 不得为空。模型必须引用启用的 `generation` 配置，调用时文本模型及地址由根目录 `.env` 决定。`Idempotency-Key` 按用户及请求内容保护，同键不同内容返回 409。

响应区分 `pending/running/insufficient/succeeded/failed/cancelled`；`insufficient` 的决策包含 `new_materials_insufficient`、`material_count_insufficient`、`relevance_insufficient`、`body_unavailable`、`duplicate_topic`、`active_task` 等稳定原因。已受理异步执行返回 `async_job_id` 和 `resource_id`；条件不足可返回无作业的创作记录。输出包括标题、候选标题、摘要、大纲、正文、关键词、封面建议、文章/修订 ID 和素材/修订引用；封面建议不表示图片已生成。所有端点分别受 `creation:read`、`creation:write` 约束。

`GET /creation-tasks/models` 供有 `creation:write` 权限的用户选择启用的生成配置；`GET /articles/{id}` 需要 `article:read`，返回当前草稿及其引用的素材历史正文和来源；`GET /materials/{id}/articles` 需要 `material:read` 和 `article:read`，返回反向引用。全库规则记录检索模式和降级原因，候选和采用记录包含具体修订及相关度。规则可用 PUT 完整更新或 PATCH 局部更新。

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

阶段 6 已实现下列端点。保存和审核在同一文章锁下复验当前修订；AI 编辑仅返回建议，用户采用后需另行保存新版本并提审。

| 方法 | 路径 | 权限及用途 |
| --- | --- | --- |
| `GET` | `/articles` | `article:read`；按状态、来源、创建时间筛选，创建时间及 ID 倒序分页 |
| `POST` | `/articles` | `article:write`；创建人工草稿及首修订，201 |
| `GET` | `/articles/{id}` | `article:read`；当前版本及引用素材的历史正文，已实现 |
| `GET` | `/articles/{id}/revisions` | `article:read`；修订历史按版本号倒序分页 |
| `GET` | `/articles/{id}/revisions/{revision_id}` | `article:read`；特定历史修订及该版本引用 |
| `POST` | `/articles/{id}/revisions` | `article:write`；基于当前修订保存新修订，201 |
| `POST` | `/articles/{id}/ai-actions` | `article:write`；返回基于指定修订的 AI 建议，不自动保存 |
| `POST` | `/articles/{id}/submit-review` | `article:write`；提交指定当前修订审核，200 |
| `GET` | `/reviews/queue` | `article:review`；按提审时间及文章 ID 升序分页 |
| `GET` | `/article-revisions/{revision_id}/reviews` | `article:read`；查询指定修订的审核历史 |
| `POST` | `/article-revisions/{revision_id}/reviews` | `article:review`；对当前待审修订提交人工结论，201 |

所有写请求要求已登录并通过 CSRF 校验。分页使用 `page`、`page_size`，响应为 `items/total/page/page_size`；时间为带时区 UTC ISO 8601。文章列表的公众号和发布时间筛选依赖阶段 7，当前契约不提供这两个筛选。版本内容包含 `title`、`author`、`keywords`、`summary`、`body_markdown`、`cover_object_id`、`layout_config`，以及按顺序排列的 `materials`，每项必须明确 `material_id` 与属于该素材的 `material_revision_id`；同一素材不能重复引用。人工创建及保存新版本返回 `article_id`、`current_revision_id`、`status=draft` 和完整 `revision`。

保存新版本请求必须提交 `base_revision_id`。服务端在同一事务中锁定文章、比较基准、写新版本和引用；不匹配返回 HTTP 409，`error.code=revision_conflict`，`field_errors` 标识 `base_revision_id`。调用方随后读取 `GET /articles/{id}` 和版本历史，不能自动覆盖。提审请求也须提交 `base_revision_id`；审核提交的路径本身绑定 `revision_id`，服务端须校验它仍是当前待审修订，否则返回相同版本冲突；状态不允许时返回 409 `invalid_article_state`。401、403、404、422 使用统一错误信封。

AI 编辑请求为 `base_revision_id`、`action`、`model_config_id`、可选 `selected_text` 和 `instruction`。`action` 为 `polish/continue/expand/shorten/rewrite/title/summary`；响应带文章、基准修订、动作、建议及模型配置版本，用户自行决定采用并另行保存。建议本身不创建文章修订或审核记录。

审核 `checklist` 固定 key 为 `title`、`content`、`facts`、`citations`、`image_copyright`、`account_compliance`、`layout`，值为 `pass/fail/not_applicable`。通过时每项必须为 `pass`，仅 `image_copyright` 可为 `not_applicable`；退回和驳回允许部分检查项，但 `comment` 必须含非空意见。审核记录绑定操作者、动作、意见及明确修订；审核历史不能改写。

| 操作 | 原状态 | 新状态 | 版本及审核语义 |
| --- | --- | --- | --- |
| 新建人工草稿 | 无 | `draft` | 创建首修订 |
| AI 创作成功 | 无 | `pending_review` | 阶段 5 已实现，首修订进入审核队列 |
| 保存编辑 | `draft/pending_review/approved/returned/rejected` | `draft` | 新建修订，旧版本和旧审核保留；新版本必须重新提审 |
| 提交审核 | `draft/returned/rejected` | `pending_review` | 仅提交当前修订；退回或驳回后可修改并复审 |
| 审核通过/退回/驳回 | `pending_review` | `approved/returned/rejected` | 必须审核当前修订；记录对应结论 |

“修改后待复审”表示保存新修订后的 `draft` 及其再次提审后的 `pending_review`，不是独立状态。旧批准始终只对旧修订有效；发布须单独验证当前版本已经过人工批准。`published` 的后续修改和发布状态由阶段 7 的发布契约处理，本阶段不声明它可直接保存或提审。

审核请求包含 `action`（`approve`/`return`/`reject`）、`checklist` 和 `comment`。退回/驳回需填写意见；通过动作只能作用于当前待审核版本。新版本提交后必须重新审核，旧版本审核记录保留但不能授权新版本发布。

补充接口：`GET /articles/models`（`article:write`）只返回启用的生成模型 ID、名称及模型名；`POST /articles/preview`（`article:read` + CSRF）接收 Markdown 与排版配置并返回 HTML；`GET /files/{id}/image` 要求文章阅读权限，且图片由当前用户上传或已被文章修订引用，返回短期下载重定向，禁止缓存。保存图片引用时复验同一访问边界，不能借保存文章取得任意文件访问权。

`layout_config` 固定字段：`template=classic/news/minimal`、`font_family=sans-serif/serif`、`font_size=12..24`、`line_height=1.2..2.5`、`paragraph_spacing=0..40`、`image_style=square/rounded`。缺省按经典模板填充；未知样式及任意 CSS 被拒绝。预览使用 CommonMark，禁用原始 HTML，仅允许 HTTP/HTTPS 链接与受控图片路径；不执行原始脚本。编辑区可保留原始文本，转换结果将其作为文本显示。手机预览直接使用同一转换端点结果，iframe 禁用脚本。AI 请求期间释放数据库事务，返回后再次检查版本，过期建议返回 409；模型错误、预算与非法输出返回脱敏 503。

### 3.6 账号、发布与统计

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/wechat-accounts`、`/wechat-accounts/{id}` | 账号列表/详情及权限摘要 |
| `POST` | `/wechat-accounts` | AppID/AppSecret 直连接入；密钥只写 |
| `PUT` | `/wechat-accounts/{id}/credentials` | 重新录入密钥接入；无 OAuth 回调 |
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
| `GET/PUT` | `/notifications/preferences` | 当前用户的通知偏好 |
| `GET` | `/notifications/channels` | 通知渠道可用能力 |
| `GET` | `/settings/operation-logs` | 按用户、模块、结果和时间筛选操作日志 |
| `GET` | `/settings/runtime`、`/settings/outbox` | 超时作业、未知外部结果及脱敏投递记录 |
| `POST` | `/settings/runtime/recover-stale` | 安全回收超时任务；提交中的外部写入转未知 |
| `POST` | `/settings/outbox/{id}/retry` | 仅恢复明确投递失败且原作业仍待执行的事件 |
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



阶段 7 自有公众号直连的已确定契约与权限边界见 [微信直连设计](wechat-direct-design.md)。账号管理使用 account:read/write；发布查询使用 publish:read，创建/确认/取消使用 publish:confirm，重试/核对使用 publish:execute；写操作均要求 CSRF。旧 authorization/callback 返回 410 direct_mode_no_oauth。


### 个人订阅号草稿交付（7.14–7.19）

前缀 `/wechat-draft-deliveries`，查询用 `publish:read`，写入用 `publish:confirm` + CSRF，不要求 `publish:execute` 或账号 freepublish 权限。账号需 active 且草稿读取可用；只读检测不承诺写入，微信拒绝时保留具体错误。

| 方法 | 路径（相对前缀） | 行为 |
| --- | --- | --- |
| GET | 空路径、`/{id}` | 分页交付/详情；按 article_id、account_id 筛选 |
| POST | 空路径 | 202；当前人工批准的 article_revision_id、account_id、confirm_sync=true、note，事务创建交付/job/outbox |
| GET | `/{id}/attempts` | 尝试历史，不暴露用于核对的私有正文快照 |
| POST | `/{id}/retry` | 202；只允许明确失败，复验版本及账号，新增任务及尝试 |
| POST | `/{id}/cancel` | 仅 pending/preparing 可取消 |
| POST | `/{id}/reconcile` | outcome=query 或 not_synced；后者要求非空 note 说明后台核对依据 |
| POST | `/{id}/manual-published` | content_matches_revision=true、mp.weixin.qq.com HTTPS article_url、非空 note；人工登记来源 operator |

创建、重试支持 Idempotency-Key；同键同内容重放原对象，异内容409。状态为 pending/preparing/syncing/unknown/awaiting_manual_publish/manual_published/failed/cancelled。同步成功不更新文章为 published；人工登记成功才更新对应当前修订文章并明确来源。unknown 只能先核对；最多查询400组，未完整覆盖或无唯一匹配时保持未知，不能直接重试。所有已审版本、账号、图片格式和长度由服务器校验；syncing/unknown 期间保存文章返回409 draft_delivery_in_progress。文章列表/详情新增独立 draft_summary，不能把草稿计入 publish_summary 或发布成功数。


## 阶段8：工作台、统计、通知与设置

统计口径和支持的筛选矩阵见 [运营设计](operations-design.md)。查询时间区间使用IANA时区的本地日期[start_date,end_date)，默认最近30天，最多366天。报表在可重复读快照内聚合并分页；导出复用同一事实查询、不受当前页影响，超过50000行明确要求缩小范围。CSV文本处理公式前缀，不可用指标为空而非0。

| 接口 | 权限及行为 |
| --- | --- |
| GET /platform | 登录；名称/介绍/文字标识/时区，应用导航和工作台使用 |
| GET /dashboard | 登录；仅聚合用户有业务读取权限的领域，缺少权限的计数为null，明细不返回 |
| GET /analytics/{kind} | analytics:read + 对应领域read；collection/materials/creation/reviews/publishing/accounts；统一items/summary/trend/filters及分页 |
| GET /analytics/{kind}/export | analytics:read + analytics:export + 对应领域read；全部筛选明细CSV |
| POST /analytics/accounts/{id}/collect-metrics | analytics:read + account:write + CSRF；北京昨日/此前7天内单日，只读微信图文累计指标，缺失字段保留null及原因 |
| GET/PUT /settings/platform | settings:read/write；PUT含version，过期409，无效IANA时区422；写入审计 |
| GET /settings/integrations | settings:read；微信/模型/搜索/存储/向量配置摘要及实际管理入口，不返回环境密钥 |
| POST /settings/integrations/storage/test | settings:write + CSRF；有界只读检查存储桶，不创建或写对象 |
| POST /settings/integrations/embedding/test | settings:write + CSRF；实际向量请求和1024维检查，失败脱敏 |
| GET /settings/permissions | role:read；可分配权限目录 |
| GET /settings/operation-logs | operation_log:read；page/page_size，action/object_type/object_id/user_id/result/start/end筛选，详情脱敏 |
| GET /settings/jobs | operation_log:read；跨用户任务监控，仅安全状态字段，按status/job_type筛选；不返回payload或原始异常 |
| GET /notifications | 登录；仅本人及当前业务权限可见，unread_only和分页 |
| POST /notifications/refresh | 登录 + CSRF；刷新本人站内通知，批次最多500，重复事件防重 |
| POST /notifications/{id}/read | 登录 + CSRF；只标记本人且有权限的通知；重复请求保留原已读时间 |
| GET/PUT /notifications/preferences | 登录；PUT含category、channel=in_app、enabled + CSRF，保存本人偏好；不支持外部渠道422 |
| GET /notifications/channels | 登录；站内可用，邮件/微信外发未接入 |

报表示例：`GET /analytics/collection?start_date=2026-11-19&end_date=2026-11-20&timezone=Asia%2FShanghai&collection_task_id=<UUID>&page=1&page_size=20`。响应summary声明total、succeeded、failed、denominator、success_rate（无分母null）、attempts、quantity、reused_materials、by_status/source/group、failure_reasons及definition；trend按同一区间的本地日期分组。查询的支持维度以设计矩阵为准，不支持的组合422。

原users/roles和model-configs/search-configs继续复用；用户/角色变更补审计，关联不存在的角色422；平台/用户/角色的重要权限拒绝有denied审计。模型凭据引用限环境变量名、只返回已配置状态；地址不允许内嵌认证或查询密钥，自定义params尚未接入会明确拒绝。文本服务保留部署环境优先规则，向量服务由现有部署环境管理，不混用文本连接测试。

## 阶段 9 运行接口

`GET /health` 保留存活契约 `{"status":"ok"}`（不列入 OpenAPI）；`GET /ready` 检查迁移 head、数据库、Redis 和 RustFS 桶，分项返回 `ready/error_code/latency_ms`，失败为 503。探测无业务写入，响应不包含端点或凭据。业务响应头包含 `X-Request-ID` 与 `Server-Timing`。

完整目录通过当前 FastAPI 的有效路由展开生成，不把空目录检查当作通过；输出必须超过 100 个方法/路径组合并与 OpenAPI 精确一致。公开例外为登录、健康检查和文件专属授权；写接口的权限与 CSRF 见矩阵。客户端继续解析统一错误信封，未知错误码显示服务端说明，非 JSON 错误使用状态码兜底。
