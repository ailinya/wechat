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
| `GET/POST` | `/collection-sources` | 来源列表/新增来源 |
| `PATCH/DELETE` | `/collection-sources/{id}` | 修改/停用来源 |
| `POST` | `/collection-sources/{id}/test` | 测试来源连接 |
| `GET/POST` | `/collection-tasks` | 查询/创建采集任务 |
| `GET/PATCH/DELETE` | `/collection-tasks/{id}` | 查看、修改、删除/停用任务 |
| `POST` | `/collection-tasks/{id}/runs` | 立即执行采集任务 |
| `GET` | `/collection-runs`、`/collection-runs/{id}` | 执行记录与详情 |
| `GET` | `/collection-results`、`/collection-results/{id}` | 结果列表与详情 |
| `POST` | `/collection-results/{id}/materialize` | 单条结果入库为素材 |
| `POST` | `/collection-results/bulk-materialize` | 批量入库，body 为 `result_ids` |
| `POST` | `/collection-results/{id}/ignore` | 忽略结果 |
| `POST` | `/collection-results/{id}/retry-parse` | 重试正文解析 |

采集任务创建请求包含名称、关键词、来源 ID、来源类型/范围、时间范围、频率与时区、自动入库、自动创作开关和启停状态。列表筛选支持状态、来源和时间；执行结果保留原文 URL、发布时间、采集时间、解析状态、去重候选和失败原因。

### 3.3 素材、文件和检索

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET/POST` | `/materials` | 查询/手工新建素材 |
| `GET/PATCH/DELETE` | `/materials/{id}` | 素材详情、更新、删除 |
| `POST` | `/materials/{id}/archive` | 归档素材 |
| `GET` | `/materials/{id}/relations` | 重复、更新和相关素材关系 |
| `GET` | `/materials/{id}/articles` | 被引用文章和版本 |
| `GET/POST` | `/material-categories`、`/tags` | 分类/标签查询和维护 |
| `POST` | `/materials/search` | 关键词与向量混合检索预览 |
| `POST` | `/files/upload-authorizations` | 获取限定对象键、类型和大小的短时上传授权 |
| `POST` | `/files/complete` | 上传完成后校验并登记对象元数据 |
| `GET` | `/files/{id}/download-authorization` | 获取受控短时下载授权 |

素材搜索请求字段：`query`、`scope`、`from`、`to`、`statuses`、`top_k`、`min_relevance`、`keyword_mode`。响应包含素材 ID、标题、匹配片段、相关度、来源和发布时间。创作接口必须提交最终选择的 `material_ids`，服务端持久化检索/采用关系。

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
| `GET/POST` | `/model-configs` | 查询/新增模型配置 |
| `PATCH` | `/model-configs/{id}` | 修改模型配置 |
| `POST` | `/model-configs/{id}/test` | 测试模型连接 |
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
POST /collection-tasks/{id}/runs
→ 创建 collection_run + async_job + outbox_event
→ Celery Worker 执行来源适配器
→ 保存 collection_results 和解析状态
→ 去重候选匹配、自动入库或等待人工选择
→ 创建 material/material_revision
→ 异步生成 material_chunks embedding
→ 满足规则时创建 creation_task
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

