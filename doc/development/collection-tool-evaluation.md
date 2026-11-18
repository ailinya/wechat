# 采集工具选型评估记录（任务 3.13）

评估时间：2026-11-18。固定标注样例集见 [collection-samples.json](collection-samples.json)，
逐例机器结果见 [collection-tool-eval-results.json](collection-tool-eval-results.json)，
重跑方法见文末。评估环境：Windows 11，直连公网（无代理），`feedparser 6.0.14`、
`trafilatura 2.3.1`（安装于隔离 venv，**未加入生产依赖**）。

## 结论（正式选型）

| 用途 | 候选 | 决定 | 依据 |
| --- | --- | --- | --- |
| RSS 解析 | feedparser | **选定** | 5 个真实中文 feed 中 3 个完整解析（sspai/ifanr/solidot），2 个失败均为站点侧限制（36氪 JS 挑战页、机器之心 XML 非法），非 feedparser 缺陷 |
| 网页正文提取 | Trafilatura | **选定**（附限制） | 15 篇真实文章中 12 篇正文/日期正确；2 类已知限制见下（标题 JS 污染、错误内容不报错），需按限制补质量校验 |
| 主题搜索 | Tavily Search | **选定**（附费用/配额监控） | 4 个固定中文查询全部返回高相关中文结果（0.40–0.84 分），官方站点召回准确，域名过滤实测生效；延迟 0.5–4.3s |
| 素材分析模型（LLM） | DeepSeek deepseek-chat | **选定**（3.28 补验） | 用户补齐凭据后，两例中文结构化分析与引用定位通过，实际 Worker 闭环成功；真实延迟、用量及语义覆盖限制见 [增强验收](phase-03-enhancement.md) |

按任务要求，feedparser 与 trafilatura 的**正式选型通过后**方可引入生产依赖（3.18/3.19 落地时执行）；
Tavily 为 HTTP API 无需新增 Python 依赖，凭据经 `TAVILY_API_KEY` 环境变量注入（本轮实测使用环境
既有 key，值不落库不入文档）。

## feedparser 逐例结果（RSS，5 例）

| 样例 | 来源 | 结果 | 条目数 | 首条目 | 延迟 |
| --- | --- | --- | --- | --- | --- |
| rss-1 | 少数派 feed | 通过 | 10 | 标题/链接/发布时间完整 | 203ms |
| rss-2 | 爱范儿 feed | 通过 | 20 | 完整 | 437ms |
| rss-3 | Solidot index.rss | 通过 | 20 | 完整 | 233ms |
| rss-4 | 36氪 feed | 失败（站点限制） | 0 | — | 156ms |
| rss-5 | 机器之心 rss | 失败（站点限制） | 0 | — | 218ms |

- rss-4：36氪对非浏览器 UA 返回 HTML JS 挑战页（`text/html`，非 XML），feedparser 报
  `not well-formed`。**这是站点反爬，不是工具限制**；后续 3.18 需按「站点不可用」明确记录，不重试伪装 UA。
- rss-5：机器之心 `/rss` 重定向后返回非法 XML（8:82 invalid token）。同为站点侧问题。

## Trafilatura 逐例结果（正文提取，15 例）

| 样例 | 类别 | 站点 | 正文 | 日期 | 标题 | 延迟(总) | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| off-1 | 官方 | cac.gov.cn | 1632 字 ✓ | 2026-10-19 ✓ | 干净 ✓ | 438ms | 通过 |
| off-2 | 官方 | cac.gov.cn | 7031 字 ✓ | 2026-09-18 ✓ | 干净 ✓ | 61ms | 通过 |
| off-3 | 官方 | stats.gov.cn | 7346 字 ✓ | 2026-11-16 ✓ | **JS 污染** | 608ms | 限制 |
| off-4 | 官方 | stats.gov.cn | 5149 字 ✓ | 2026-11-16 ✓ | **JS 污染** | 547ms | 限制 |
| off-5 | 官方 | stats.gov.cn | 3105 字 ✓ | 2026-11-16 ✓ | **JS 污染** | 297ms | 限制 |
| ind-1 | 行业 | ifanr.com | 4064 字 ✓ | 2026-11-18 ✓ | 干净 ✓ | 202ms | 通过 |
| ind-2 | 行业 | ifanr.com | 17467 字 ✓ | 2026-11-18 ✓ | 干净 ✓ | 141ms | 通过 |
| ind-3 | 行业 | ifanr.com | 4837 字 ✓ | 2026-11-17 ✓ | 干净 ✓ | 561ms | 通过 |
| ind-4 | 行业 | sspai.com | 7224 字 ✓ | 2026-11-18 ✓ | 干净 ✓ | 1141ms | 通过 |
| ind-5 | 行业 | sspai.com | 9874 字 ✓ | 2026-11-17 ✓ | 干净 ✓ | 358ms | 通过 |
| news-1 | 新闻 | chinanews.com.cn | 1834 字 ✓ | 2026-11-17 ✓ | 干净 ✓ | 235ms | 通过 |
| news-2 | 新闻 | news.cctv.com | 481 字 ✓ | 2026-11-18 ✓ | 干净 ✓ | 2436ms | 通过 |
| news-3 | 新闻 | jiemian.com | 1409 字 ✓ | **2023-08-17** ✓ | 干净 ✓ | 188ms | 通过（旧文如实召回） |
| news-4 | 新闻 | solidot.org | 790 字 **✗** | 2026-11-17 | 取到站名 | 233ms | **限制：错误内容不报错** |
| news-5 | 新闻 | bbc.com/zhongwen | 抓取超时 | — | — | 21062ms | 失败（网络限制，符合预期） |

关键限制（必须由 3.19 落实质量校验，不得由工具静默通过）：

1. **stats.gov.cn 标题 JS 污染**（off-3/4/5）：该站模板把标题放在 `document.write` 的 JS 变量里，
   Trafilatura 元数据标题被污染为 `var title1 = '...'`；正文与日期提取正常。落地时标题需回退取
   `<title>` 标签并清洗 JS 片段，污染结果标 `needs_review`。
2. **Solidot 错误内容不报错**（news-4）：Trafilatura 返回站點描述（790 字）而非新闻正文且**未报错**，
   仅靠长度阈值（≥200 字）会误判通过。落地时需比较提取文本与元数据 description、并做站点模板适配；
   无法可靠提取的来源按明确失败处理。
3. **BBC 中文直连超时**（news-5）：本网络 21s 超时。记录为网络可达性限制，不代表工具缺陷；受影响来源
   在配置中标记不可用，不自动重试超预算。

## 栏目/列表页链接发现（2 例）

| 样例 | 页面 | 新鲜链接 | 延迟 | 判定 |
| --- | --- | --- | --- | --- |
| list-1 | stats.gov.cn/sj/zxfb/ | 15 条（含 t20261116_*.html） | 1467ms | 通过 |
| list-2 | cac.gov.cn/ 首页 | 4 条（c_*.htm） | 47ms | 通过 |

链接发现对静态服务端渲染页可行；`thepaper.cn`（SPA）、`xinhuanet.com`/`people.com.cn`
（403 反爬）不适用，见限制记录。

## Tavily Search 逐例结果（4 个固定查询，真实凭据）

| 查询 | 延迟 | Top 结果域名 | 预期域名命中 | 判定 |
| --- | --- | --- | --- | --- |
| q-1 国家统计局 10 月份国民经济运行 | 516ms | stats.gov.cn（0.809）、sohu、xinhuanet | stats.gov.cn ✓ | 通过 |
| q-2 未成年人网络保护 征求意见 | 2875ms | baike、people.com.cn、cac.gov.cn（0.71）、thepaper | cac.gov.cn ✓ | 通过 |
| q-3 英伟达 黄仁勋 回归 董事会 | 4297ms | tradingkey、sohu、zhihu、mydrivers、bbc | 预设行业站（ifanr 等）未进 Top5 | 未达预设预期* |
| q-4 同 q-1 + include_domains=[stats.gov.cn] | 4329ms | **全部 5 条来自 stats.gov.cn** | ✓ | 通过（域名过滤生效） |

- \*q-3：返回结果均为高相关中文页面，中文检索能力本身正常；标注预期（特定行业站进 Top5）过严，
  如实记录为「特定站点召回取决于其索引权重」。**服务端仍须对搜索结果做统一域名补验**（q-4 证明
  提供方过滤可生效，但设计要求不信任单一来源）。
- 用量：basic 深度响应未返回 token/额度字段（`request_id`/`response_time` 有返回）。**费用与配额
  需在 Tavily 控制台核对；实现按调用次数计预算**（设计默认每次运行最多 3 次搜索请求，重试计入）。
- 中文相关性：全部 4 查询返回中文来源且分数区间合理（0.40–0.84），无乱码或明显不相关结果。

## 分析模型历史阻塞记录（3.13）与解决（3.28）

- 检查了 `ZHIPUAI_API_KEY`、`GLM_API_KEY`、`BIGMODEL_API_KEY`、`OPENAI_API_KEY`、
  `ANTHROPIC_API_KEY`、`DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`、`MOONSHOT_API_KEY`，
  在 3.13 初次评估时**均未设置**。
- 因此「analysis 模型的中文结构化输出和原文引用能力」**未验证**；按任务要求不以 fixture 冒充真实
  提供方通过。当时分析模型选型保持未定，3.28 在缺少真实证据时保持未完成。

2026-11-18，用户补齐 `DEEPSEEK_API_KEY` 后完成 3.28 补验，选定 DeepSeek `deepseek-chat`（analysis 用途，OpenAI 兼容协议）。[真实模型证据](analysis-model-live-evidence.json)含固定中文样例与官方正文，延迟分别 1703ms、3297ms，用量分别 489、1734 token；[实际 Worker 证据](analysis-worker-live-evidence.json)确认 API/outbox/Redis/Worker/模型/数据库闭环成功，用量 461 token。引用均可在原文定位，但不等于完整语义支持或外部事实核验，建议仍需人工审核。历史未验证记录保留，不倒写为初次评估即通过。

## 已知缺口（样例集层面）

1. 跨站转载对（同事件两站）本轮未固定，影响 3.21 判重验证，后续补充样例。
2. 无「正文完全无日期」样例：本轮 15 篇均取到日期（含界面 2023 旧文的真实日期）。后续补充。
3. 时间缺失/动态页面（SPA）、登录墙站点不在本轮范围（设计已声明不交付）。

## 正式配置（固定，供 3.16–3.19 落地）

| 项 | 值 |
| --- | --- |
| RSS 解析 | feedparser ≥6.0（3.18 引入生产依赖；站点 JS 挑战/非法 XML 按「来源不可用」记录） |
| 正文提取 | trafilatura ≥2.3（3.19 引入生产依赖；标题回退 `<title>`、description 对比校验、`needs_review` 标记） |
| 搜索 | Tavily Search HTTP API（basic 深度，`max_results=5`，支持 `include_domains`/`topic`）；凭据仅经 `TAVILY_API_KEY` 环境注入，不回显不落库 |
| 分析模型 | DeepSeek `deepseek-chat`；接口 `https://api.deepseek.com/v1/chat/completions`，用途 analysis，凭据引用 `DEEPSEEK_API_KEY`；真实证据与限制见上文 |
| 既有能力 | 阶段 3 的 `document_parser`（HTML/DOCX/PDF）保留；3.19 网页提取切换到 trafilatura 后做回归 |

## 重跑方法

```bash
uv venv "$TEMP/wetchat-tool-eval"
uv pip install --python "$TEMP/wetchat-tool-eval" feedparser trafilatura requests
# TAVILY_API_KEY 来自环境；分析模型凭据缺失时自动记录阻塞
"$TEMP/wetchat-tool-eval/Scripts/python.exe" backend/scripts/evaluate_collection_tools.py
```

样例 URL 冻结于 `collection-samples.json`（2026-11-18 版）；重跑不得更改 URL，只能追加样例并注明。
