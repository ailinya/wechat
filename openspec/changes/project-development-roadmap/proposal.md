# Proposal

## Why

本变更最初将 PRD、原型和架构整理为可验证的规格与工程路线图，现已进入分阶段实施。现有采集基础需要增补主题搜索、RSS/栏目文章发现及 LLM 素材分析，使“只给主题”与“指定来源”均能生成可追溯素材，补齐自动分类、新进展判断和失败恢复的契约。

## What Changes

- 定义从工程基础到核心闭环、运营管理和智能化增强的分阶段实施顺序。
- 为整个项目建立能力规格，明确正常、失败、并发、权限和恢复场景；各阶段实施以对应规格为行为契约。
- 每个阶段分别列出前端、后端、数据库、API、测试、前置依赖和阶段验收标准。
- 将工作项细化为可勾选、可单独交给 Codex 实施的任务，并注明需遵循的既有设计文档。
- 明确先完成安全、数据模型、接口契约和集成基础，再逐步交付真实业务流程；阶段完成以可运行、可验证的纵向能力为准。

## Capabilities

本次增量仅更新设计与任务：在阶段 3 追加 3.13–3.28，保留旧编号与完成记录；采用固定采集流程，公共模型能力提前供采集与后续创作复用，不引入采集 Agent。同步 PRD、架构和追踪矩阵；实际依赖安装、迁移和业务开发由后续任务执行。

### New Capabilities

- `access-control`：登录、会话、用户角色和服务端操作权限。
- `application-shell`：八模块导航、页面状态、查询恢复与真实操作反馈。
- `api-contract`：统一请求响应、分页、错误、时间及异步契约。
- `async-execution`：持久任务状态、可靠投递、幂等及失败恢复。
- `file-storage`：受控文件授权、上传登记与附件访问。
- `collection-management`：指定来源/主题搜索、网站范围、文章链接发现、调度、阶段执行结果及入库选择。
- `material-analysis`：可选 LLM 摘要/分类/相关性/事实提取、输入版本、人工建议采用、失败恢复与预算控制。
- `material-library`：素材正文版本、去重、新进展、分类收藏及引用溯源。
- `material-search`：中文关键词、语义与混合检索、修订隔离及候选选择。
- `ai-creation`：自动规则、条件判断、Agent 创作、引用及任务恢复。
- `article-review`：文章编辑、排版、版本并发控制、人工审核与复审。
- `wechat-accounts`：公众号接入、权限检测、默认配置与素材同步。
- `controlled-publishing`：发布订单、运营确认、定时执行、结果核对及重试。
- `operations-analytics`：工作台、业务统计、账号指标、筛选和导出。
- `platform-management`：提前提供公共模型及搜索配置、用途隔离、连接测试与预算，后续扩展通知、操作日志和任务监控。
- `service-operability`：健康状态、部署、迁移、备份恢复与真实接入验收。
- `intelligence-assistance`：后续主题推荐、深度关联、质量建议与运营分析增强。

### Modified Capabilities

无已发布主规格需要修改；`openspec/specs/` 仍为空。此次调整同一进行中 change 的 ADDED Requirements，并新增 `material-analysis`，不误写为针对不存在主规格的 MODIFIED Requirements。

## Impact

- 维护 OpenSpec 规划文档：`proposal.md`、`design.md`、`tasks.md`，以及 `specs/<capability>/spec.md` 下的 17 份能力规格。
- 规划覆盖 React + TypeScript + Vite、FastAPI 模块化单体、PostgreSQL + pgvector、Celery + Redis、RustFS、LangGraph，以及微信和模型服务适配边界。
- 实施依据为 `AGENT.md`、`doc/instruction/PRD.md`、`doc/architecture/*.md` 和 `doc/html/*.html`；原型未覆盖的采集增强交互以增量设计为准。本次只交付文档增量，已有功能保留，新搜索/分析能力尚未实现。
- 后续增量涉及采集/素材/设置的 API、数据库、Worker 和页面；旧请求保持默认兼容，数据库在当前 head 后新增迁移，阶段 5 复用模型配置而不重复建表。
- Tavily Search、feedparser、Trafilatura 仅为候选；正式采用须经过中文来源样例验证并记录费用、限制与真实连通证据。动态网页渲染、扫描 PDF OCR 和自主补搜不包含在本期。
