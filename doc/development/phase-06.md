# 阶段 6：文章编辑、排版与人工审核

日期：2026-11-19。变更 `project-development-roadmap`，任务 6.1–6.10。

## 已实现

- 内容管理列表支持状态、人工/生成来源、创建时间范围及稳定分页；筛选与返回上下文保存在地址中。
- 人工草稿、编辑保存、版本历史及素材修订引用均为真实 API。保存与引用同事务写入，基准修订不符返回 `409 revision_conflict`；页面保留本地修改并展示服务器最新版本供合并。
- 生成模型提供润色、续写、扩写、缩写、改写、标题及摘要建议。建议不写文章，用户采用到编辑区后仍须保存；模型调用在数据库事务之外，返回后复验版本。
- 排版保存模板、字体、字号、行距、段落间距与图片样式。CommonMark 转换禁用原始 HTML、限制链接协议；手机预览使用同一 API 的 HTML，并禁用 iframe 脚本。
- 图片上传复用原文件授权组件；已登记图片可设为封面或插入正文。永久受控图片路径在访问时换取短期授权，保存时检查上传人或已存在的文章引用，不能借文章保存取得任意私有图片。
- 审核队列、完整检查项、退回/驳回意见及历史均绑定明确修订。编辑、提审和审核使用相同文章行锁；新版本回到草稿，旧批准保留在旧版本，不能放行新版本。审核通过展示“审核通过／待发布”，实际发布属于阶段 7。

## 验证证据

| 验证 | 结果 |
| --- | --- |
| 阶段 6 PostgreSQL 契约及集成测试 | **11 passed，0 skipped**；含迁移回退/再升级、跨文章修订约束、并发保存、编辑与审核竞争、复审、权限、AI 超时/非法输出/过期建议、脚本与样式注入、历史素材正文及图片访问 |
| 创作回归 | `test_creation_schema.py`、`test_creation_integration.py` **13 passed**；扩大回归在最后两项阶段 6 用例加入前合计 22 passed |
| 前端组件 | **43 passed**；新组件覆盖保存冲突保留本地内容、AI 采用后显式保存、排版参数提交和审核权限/意见 |
| 生产构建 | `pnpm run build` 通过，包含 TypeScript 检查 |
| 静态检查 | `pnpm run lint` 返回 0；仍有非阻断的 hooks/刷新边界等警告，未作为零警告验收 |
| 浏览器 + 真实 API/独立 PostgreSQL | `article-review.spec.ts` **1 passed**：人工草稿 v1→退回→保存 v2→复审通过→刷新与历史意见→保存 v3 后回到草稿；取消离开保留未保存正文，排版可恢复 |
| 视觉检查 | 已检查桌面及 390px 窄屏截图；证据生成在 `test-results/article-review-desktop.png`、`article-review-mobile.png` |

后端模型与下载签名采用确定性替身；本阶段未重复执行真实模型调用或真实 RustFS 上传，未接入微信和执行发布。浏览器验证使用真实文章/审核 API，不使用成功状态拦截。

## 数据与状态

新增迁移 `0017_article_reviews`：创建 `reviews`，以 `(article_revision_id, article_id)` 外键绑定修订；添加 `articles.submitted_at`、列表与审核队列索引，并回填既有待审文章的提交时间。已有 revision 的 `layout_config`、封面与引用结构复用 `0016_articles`，不修改历史迁移。

允许的流程：人工创建 `draft`；提交 `pending_review`；人工结论 `approved/returned/rejected`。保存新修订统一回到 `draft`，再次提交后为待复审的 `pending_review`。生成文章依旧直接进入 `pending_review`。当前不允许直接修改已发布文章；后续发布单必须复验当前版本及对应人工批准。

本次只迁移独立测试库，未升级业务库。业务部署前先备份，再在 backend 执行 `uv run alembic upgrade head`。回退应用优先保留新增审核数据；破坏性 downgrade 会删除审核历史，只在独立空测试库验证过，不用于有历史的业务库。

## 复现

可用专用 `TEST_DATABASE_URL` 直接执行 `uv run pytest tests/test_article_contract.py tests/test_article_review.py -q`。fixture 会重建该测试库 schema，不能指向业务库。

本次独立容器为 `wetchat-phase06-postgres`（pgvector/pg16，宿主仅绑定 `127.0.0.1:55437`，无业务卷，数据库 `wetchat_phase06_test`）。已有数据库端口冲突且根目录配置与旧卷凭据不一致，因此使用该隔离实例验证，未更改旧卷密码或数据。

PowerShell 在 backend 设置 `$env:POSTGRES_PORT='55437'` 后运行 `uv run python scripts/test_article_review.py` 可复现。本地测试容器采用仅本机访问的 trust 认证；正式环境仍沿用项目凭据配置。测试结束可停止该容器，不影响业务卷。

浏览器测试需独立 API 与 Vite：本次 API 8016、前端 5176，数据库 URL 指向上述测试库。设置 `E2E_BACKEND_URL=http://127.0.0.1:8016`、`E2E_BASE_URL=http://127.0.0.1:5176`、`E2E_NO_SERVER=1`，执行 `pnpm exec playwright test tests/e2e/article-review.spec.ts --workers=1`。仅使用隔离测试账号 `admin / correct-password`；这些账号不属于业务环境。

## 下一阶段

用户随后于2026-11-19确定采用自有公众号直连；阶段7实现及真实接入阻塞见 [阶段7记录](phase-07.md)。真实账号权限和发布仍不能以 fixture 结果代替验收。
