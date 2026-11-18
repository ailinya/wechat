# 采集分析与去重增量验证（3.20–3.21）

验证日期：2026-11-18。此记录仅覆盖服务实现与确定性 fixture，不代表 3.22 Worker 全流程或 3.28 增强验收完成。

## 已实现行为

- 独立分析 handler 读取已保存的正文快照；外部模型调用位于数据库事务之外。提示词将正文作为不可信资料，模型没有搜索、审核或发布工具。
- 分析记录绑定采集结果、不可变快照/hash、主题/关键词、模型配置版本和提示词版本。相同输入复用成功结果或正在执行的领取；失败尝试独立保留。
- 数据库领取限制每个逻辑分析最多 3 次尝试、每次运行最多 40 次模型请求及 600 秒窗口；默认 adapter 每次领取仅发起一次外部请求。过期领取可恢复。未知 usage 保存为空值。
- 摘要、相关性、事实输出经 schema 校验；事实引用须可在输入正文中定位。输入过大、非法 JSON/schema 或虚构引用明确失败，重试从快照恢复。
- 模型返回后复验正文和目标素材修订，过期结果标记 stale；忽略或取消的对象不因历史分析返回而恢复。
- 入库按正文 SHA-256 内容键加事务锁，跨 URL/来源完全重复复用同一素材，各采集结果保留来源关联。内容 hash 变化不再自动产生 update_of。
- 历史候选查询按 URL、标题或关键词选择最多 5 个当前修订。完全重复跳过模型；语义 duplicate/uncertain 或比较失败返回 review_required，保留原结果。
- new_progress 必须有当前正文可定位且旧正文未包含的新增事实引用。只有已保存且正文/目标修订仍有效的比较记录，才可作为新进展入库依据。

## 数据库变更

- 0009 修复 collection_analyses.scope 长度不足，允许已有契约中的 collection_result。
- 0010 增加分析输入快照/hash、上下文、配置快照、领取到期时间和目标修订引用；对逻辑键及 attempt 建立唯一索引。
- 测试仅操作 Docker PostgreSQL 的 wetchat_test，连接凭据由容器环境在测试进程内读取。未迁移业务库。

## 已执行验证

数据库回归：28 项通过、0 跳过，覆盖以下文件：

- test_material_comparison_integration.py
- test_material_analysis_integration.py
- test_materialization_integration.py
- test_collection_integration.py
- test_article_extraction_integration.py
- test_discovery_integration.py

重点证据包括同正文跨来源并发只生成一份素材、分析并发只领取一次、不同主题不误用相关性、非法引用失败、失败重试保留 attempt、正文改变后 stale、历史上限 5、比较重投不重复调用、语义重复待人工以及有效新事实关联 update_of。

同时修正既有数据库测试夹具的无效用户 ID、commit 后复用关闭连接、遗漏 source_id 及删除断言捕获过宽问题；删除测试现在要求实际外键错误。

## 尚未验收

- 真实 LLM 的中文结构化输出、引用质量、延迟及用量尚未验证，fixture 不能替代提供方验收。
- 发现、提取、分析及比较服务接入统一 Worker/阶段恢复/outbox/就绪事件属于 3.22。
- 素材独立分析查询、人工采用及元数据版本保护属于 3.23。
- 前端、浏览器全流程及 Redis/Worker 故障恢复仍需 3.24–3.28 实测。
