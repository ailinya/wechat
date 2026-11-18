# 采集增强前的实现与验收证据缺口

记录时间：2026-11-18。本记录为只读代码/文档核对，不代表重新执行过测试。保留原 tasks.md 3.1–3.12 的编号、内容及勾选，不静默重写历史；后续原能力复验及增量验收以 3.26、3.28 为准。

| 事项 | 当前证据 | 处理及验收位置 |
| --- | --- | --- |
| 来源入口与文章发现 | `backend/app/modules/collection/tasks.py` 对每个来源 base_url 抓取一次，没有按 RSS 条目、栏目链接逐篇发现；不能把来源类型存在解释为 RSS 完整支持 | 3.18 加文章发现；3.26 验证 RSS 多篇及分页上限 |
| 关键词和时间配置 | schemas/service 已保存 keywords/time_range_days，但当前 collection handler 未按其筛选正文 | 3.19 落实筛选；3.26 覆盖窗口边界、日期缺失、短语匹配 |
| 跨站重复与新进展 | 当前 dedup_key 为最终 URL 的 hash；materialization_service 用同键正文 hash 是否变化决定 duplicate/update_of。它不能证明跨 URL 去重或有效新增事实，单纯页面变化可能误标进展 | 涉及原 3.7 及 material-library 规格的能力差距，3.21 补比较依据，3.26 复验原要求；不能宣称旧实现已有语义判定 |
| HTTP/解析结果 | 当前 collection handler 仅捕获 FetchError 后累计失败；fetch 返回的非重定向 HTTP 状态未在 handler 明确拒绝，且运行成功判定主要看抓取异常数 | 3.19 拒绝无效响应/正文，3.22 补阶段错误和计数，3.26 验证 HTTP 错误与解析失败不能冒充全流程成功 |
| LLM 与搜索接入 | 当前没有搜索配置、搜索 adapter、分析结果与独立重试流程 | 本次新增需求，由 3.14–3.25 实现，不回填原任务“已完成” |
| 阶段 3 验证记录 | `phase-03.md` 虽记录任务完成，但明确 PostgreSQL/Redis/RustFS 及 DB 行为/跨组件测试未执行或跳过，真实来源未验收 | 原 3.11/3.12 勾选不代表这些测试通过。3.26 必须在独立实例实际运行并记录，3.28 解决证据缺口或保持未完成；缺少真实服务不能以文档校验代替 |

新增工具评估结果将写入 `collection-tool-evaluation.md`，增强验收写入 `phase-03-enhancement.md`（均由未来任务创建）。正式依赖和目标来源未验证前，Tavily、feedparser、Trafilatura 只是候选。
