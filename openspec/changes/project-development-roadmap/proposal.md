# Proposal

## Why

项目已有 PRD、HTML 原型、系统架构、数据库和 API 设计，但尚未形成可验证的行为规格和能直接交给 Codex 分批实施的工程路线图。需要把这些材料整理为业务边界明确的能力规格与分阶段任务，减少跨层遗漏和返工。

## What Changes

- 定义从工程基础到核心闭环、运营管理和智能化增强的分阶段实施顺序。
- 为整个项目建立能力规格，明确正常、失败、并发、权限和恢复场景；各阶段实施以对应规格为行为契约。
- 每个阶段分别列出前端、后端、数据库、API、测试、前置依赖和阶段验收标准。
- 将工作项细化为可勾选、可单独交给 Codex 实施的任务，并注明需遵循的既有设计文档。
- 明确先完成安全、数据模型、接口契约和集成基础，再逐步交付真实业务流程；阶段完成以可运行、可验证的纵向能力为准。

## Capabilities

### New Capabilities

- `access-control`：登录、会话、用户角色和服务端操作权限。
- `application-shell`：八模块导航、页面状态、查询恢复与真实操作反馈。
- `api-contract`：统一请求响应、分页、错误、时间及异步契约。
- `async-execution`：持久任务状态、可靠投递、幂等及失败恢复。
- `file-storage`：受控文件授权、上传登记与附件访问。
- `collection-management`：来源、采集任务、调度、执行结果及入库选择。
- `material-library`：素材正文版本、去重、新进展、分类收藏及引用溯源。
- `material-search`：中文关键词、语义与混合检索、修订隔离及候选选择。
- `ai-creation`：自动规则、条件判断、Agent 创作、引用及任务恢复。
- `article-review`：文章编辑、排版、版本并发控制、人工审核与复审。
- `wechat-accounts`：公众号接入、权限检测、默认配置与素材同步。
- `controlled-publishing`：发布订单、运营确认、定时执行、结果核对及重试。
- `operations-analytics`：工作台、业务统计、账号指标、筛选和导出。
- `platform-management`：模型/接口/平台配置、通知和操作日志。
- `service-operability`：健康状态、部署、迁移、备份恢复与真实接入验收。
- `intelligence-assistance`：后续主题推荐、深度关联、质量建议与运营分析增强。

### Modified Capabilities

无。仓库尚无已发布的 OpenSpec 能力规格；以上为根据既有需求与设计建立的初始规格。

## Impact

- 新增 OpenSpec 规划文档：`proposal.md`、`design.md`、`tasks.md`，以及 `specs/<capability>/spec.md` 下的 16 份能力规格。
- 规划覆盖 React + TypeScript + Vite、FastAPI 模块化单体、PostgreSQL + pgvector、Celery + Redis、RustFS、LangGraph，以及微信和模型服务适配边界。
- 实施依据为 `AGENT.md`、`doc/instruction/PRD.md`、`doc/architecture/*.md` 和 `doc/html/*.html`；后续按规格及任务实施前后端、数据库迁移与集成。本次交付规划和规格文件，尚未实现产品功能。
