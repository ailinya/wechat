# 智媒助手数据库设计

## 阶段 5 实施补充

迁移 `0015_creation`、`0016_articles` 建立创作规则、规则与采集任务关系、创作任务、候选素材、输出槽位、已消费事件、文章、文章修订和文章素材引用。规则触发类型及窗口唯一约束防止重复批次；输出的任务与槽位唯一。候选记录保存素材修订和是否采用，文章引用保存实际引用的素材修订，当前文章修订必须属于该文章。文章创建时为 `pending_review`，不依赖尚未接入的公众号表。重试复用已完成槽位；显式重新生成创建关联来源任务的新记录。模型配置复用 `model_configs`，不存放明文密钥。

## 1. 目的与依据

本文定义智媒助手首期 PostgreSQL 数据模型，包括业务表、表关系、关键约束及 pgvector 用法。设计依据为 `AGENT.md`、`doc/instruction/PRD.md` 和 `doc/html/` 静态原型；原型 JSON 是演示数据，不作为生产表结构。

## 2. 数据约定

- PostgreSQL 保存业务数据、中文正文、任务记录和素材向量；图片、PDF、Word 等二进制对象存 RustFS。
- 主键使用 UUID；时间戳带时区，API 统一使用 UTC。可变记录含 `created_at`、`updated_at`，操作类记录保留操作者。
- 外键、状态、时间范围等常用筛选字段使用独立列并建立索引；仅把低频筛选、可变结构配置放 JSONB。
- 不把素材引用次数、引用文章标题数组、最近执行时间等聚合展示值保存成事实字段。
- 去重指纹用于检索候选，不直接建立全局唯一约束；这样不会把同一事件的新进展误删。

## 3. 用户与系统配置

| 表 | 主要字段 |
| --- | --- |
| `users` | `id`, `account`, `name`, `contact`, `status`, `created_at`, `updated_at` |
| `roles` | `id`, `name`, `description` |
| `permissions` | `id`, `code`, `module`, `action` |
| `user_roles` | `user_id`, `role_id`；唯一约束 `(user_id, role_id)` |
| `role_permissions` | `role_id`, `permission_id`；唯一约束 `(role_id, permission_id)` |
| `model_configs` | `id`, `provider`, `model_name`, `endpoint`, `credential_ref`, `purpose`, `parameters`, `enabled`；提前在 3.15 创建，`purpose` 区分 analysis/generation/embedding，增加配置版本与调用限额，阶段 5 复用 |
| `system_settings` | `key`, `value`, `updated_by`, `updated_at`；不得存未加密密钥 |
| `notification_preferences` | `user_id`, `event_type`, `channel`, `enabled` |
| `notifications` | `id`, `user_id`, `event_type`, `content`, `read_at`, `created_at` |
| `operation_logs` | `id`, `user_id`, `module`, `action`, `target_type`, `target_id`, `result`, `detail_redacted`, `created_at` |

## 4. 采集与素材

| 表 | 主要字段和关系 |
| --- | --- |
| `collection_sources` | `id`, `name`, `source_type`（`rss`/`web_page`）, `base_url`, `description`, `enabled`, `status`（`active`/`inactive`/`unavailable`）, `config` JSONB, `last_checked_at`, `last_success_at`, `deleted_at`（软删除）；密钥不放普通配置 |
| `collection_tasks` | `id`, `name`, `keywords` JSONB, `time_range_days`, `schedule_frequency`/`schedule_cron_expr`, `timezone`（默认 `Asia/Shanghai`）, `auto_materialize`, `auto_create`, `status`（`active`/`paused`/`archived`）, `last_run_at`, `next_run_at`, `last_window_key`/`lease_until`（去重领取）, `created_by`；任务与运行分离 |
| `collection_task_sources` | `task_id`, `source_id`；联合主键，一个任务可选多个来源 |
| `collection_runs` | `id`, `task_id`, `trigger`（`manual`/`scheduled`）, `status`（`pending`/`running`/`succeeded`/`partial`/`failed`）, `window_key`, `async_job_id`, `fetched_count`/`parsed_count`/`materialized_count`/`failed_count`, `error`, `started_at`, `finished_at` |
| `collection_results` | `id`, `run_id`, `source_id`, `title`, `url`, `summary`, `published_at`, `collected_at`, `raw_content`, `raw_object_id`, `dedup_key`（去重）, `parse_status`（`pending`/`parsed`/`failed`）, `materialize_status`（`pending`/`materialized`/`duplicate`/`new_progress`/`ignored`/`failed`）, `material_id`, `claimed_at`/`claimed_by`（领取）, `error` |
| `materials` | `id`, `title`, `summary`, `material_type`, `origin`（`collection`/`upload`/`link`/`manual`/`article`/`enterprise`）, `usage_status`（`pending_review`/`ready_to_use`/`partially_used`/`used`/`archived`/`duplicate`）, `category_id`, `current_revision_id`, `deleted_at`（软删除）, `created_by`, `created_at`, `updated_at` |
| `material_revisions` | `id`, `material_id`, `revision_no`（同一素材内唯一）, `content_markdown`, `content_hash`, `file_ids` JSONB, `created_from_result_id`, `created_by`, `created_at`；正文历史不可覆盖；`(id, material_id)` 唯一以支持当前修订归属约束 |
| `material_relations` | `id`, `source_material_id`, `target_material_id`, `relation_type`（`duplicate_of`/`update_of`/`related_to`）, `created_at`；三元组唯一防重 |
| `material_categories` | `id`, `name`, `parent_id`（不得自引用）, `sort_order` |
| `tags` / `material_tags` | 标签定义（名称唯一）和素材多对多关系（`material_id`+`tag_id` 联合主键防重） |
| `stored_objects` | `id`, `bucket`, `object_key`, `size_bytes`, `content_type`, `sha256`, `uploader_id`, `created_at`；`(bucket, object_key)` 唯一 |
| `material_files` | `id`, `material_id`, `stored_object_id`, `role`；`(material_id, stored_object_id, role)` 唯一防重，关联原始附件或素材图片 |
| `material_favorites` | `id`, `material_id`, `user_id`, `created_at`；`(material_id, user_id)` 唯一，按用户隔离 |
| `material_chunks` | `id`, `material_revision_id`, `chunk_index`, `content`, `content_hash`, nullable `embedding vector(1024)`, `embedding_model_config_id`, `embedding_config_version`, `embedding_model_name`, `embedding_dimension`, `created_at`（迁移 0013；向量可空以支持分块先建、异步回填） |

采集结果始终保留；自动或人工入库通过 `material_id` 关联素材（迁移 0004 已补 FK，软删除时置 NULL）。重复项关联已有素材；同事件新进展创建新素材，通过 `material_relations` 关联，不覆盖旧正文。采集结果支持未入库、已入库、忽略和解析失败等状态。

约束（迁移 0003）：来源/任务/运行/结果状态及 `source_type`、`trigger` 由 CHECK 约束固定；`cron` 调度必须带 `schedule_cron_expr`。任务与运行分离——任务是定义、运行是一次执行，`collection_runs.task_id` 引用任务且删除受限。部分唯一索引 `uq_collection_runs_task_window (task_id, window_key) WHERE window_key IS NOT NULL` 防止同一调度窗口重复创建 run（手动运行 `window_key` 为 NULL，不受限）。触发器 `assert_collection_task_schedulable` 阻止为 `paused`/`archived` 任务创建 `scheduled` run，手动运行仍允许。删除保留追溯：任务用 `status='archived'`、来源用 `deleted_at` 软删除；`collection_results.run_id`、`collection_task_sources.source_id` 为 `ON DELETE RESTRICT`，`collection_results.source_id` 为 `ON DELETE SET NULL`，已有运行与结果始终可解析。

素材状态遵循 PRD：待筛选、待使用、已使用、部分使用、已归档、重复素材。正文存 PostgreSQL 的 `TEXT`；原始附件和图片只存 RustFS，PostgreSQL 保存对象键、元数据与关联。

约束（迁移 0004）：`material_revisions` 以 `(material_id, revision_no)` 唯一保证修订序号不重复，正文修订不可覆盖。`materials.current_revision_id` 通过可延迟复合外键 `(current_revision_id, id) → material_revisions (id, material_id)` 约束当前修订必须属于本素材，允许在单事务内先建素材与首修订。关联表以联合主键/唯一键防重（标签、素材关系、文件、收藏）；收藏按用户隔离。删除按保留策略：素材用 `deleted_at`+`usage_status='archived'` 软删除，含修订的素材禁止物理删除（`ON DELETE RESTRICT`）；文章/采集引用在阶段 5/6 绑定修订，素材更新不改变历史引用正文。`collection_results.material_id` 外键在素材软删除时置 NULL，保留采集追溯。

约束（迁移 0005，采集增强）：新增 `model_configs`/`search_configs`（凭据仅存 `credential_ref` 引用，用途隔离 `analysis/generation/embedding`）、`collection_candidates`（`UNIQUE(run_id, normalized_url)` 运行内防重）、`collection_stage_attempts`、`collection_snapshots`（不可变正文快照）、`collection_analyses`（绑定修订与模型配置版本，`logical_key` 索引用于复用/领取）与 `material_ready_events`（`event_key` 唯一保证素材就绪事件幂等）。对既有表只做增量 `ALTER`：`collection_sources` 补 `page_kind`/栏目选择器，`collection_tasks` 补 `mode/topic/allowed_domains/limits/analysis_*/search_config_id`，`collection_runs` 补 `end_reason`/阶段计数/`config_snapshot`，`materials` 补 `metadata_version`/`manual_fields`。旧数据由 `NOT NULL DEFAULT` 回填（`mode='source'`、`analysis_enabled=false`、`page_kind='article'`），不重跑历史任务，不改 0003/0004。

### pgvector 约定

`material_chunks.embedding` 使用 pgvector。迁移 0013 启用 `vector` 扩展并创建修订级分块表；embedding 暂允许 NULL，以便作业先持久化分块、再回填向量。`(material_revision_id, chunk_index, embedding_model_config_id, embedding_config_version)` 唯一防止同修订、同配置版本重复分块。迁移 0014 的 `material_embedding_runs` 以修订和配置版本唯一，记录异步任务、尝试状态及脱敏失败码。当前根目录 `.env` 指定 Qwen MaaS `qwen3.7-text-embedding-flash`、`EMBEDDING_DIMENSION=1024`，原生 API 基址为 `EMBEDDING_BASE_URL`，凭据引用 `OPENAI_API_KEY`；API key 不写入仓库。2026-11-18 实测 HTTP 200 并返回 1024 维，证据见 `doc/development/embedding-model-live-evidence.json`。此前 `text-embedding-v3` 使用 DashScope 公共兼容端点的探针曾返回 `401 invalid_api_key`，该结果不验证当前 Qwen 配置。字段类型为 `vector(1024)`，不同维度不能混在同一向量列。配置版本与维度写入每个 chunk，确保不能把其他模型空间的向量混合比较。换模型或维度时使用新列/新表并重建向量，验证完成后再切换；正文修订创建新 chunk，保留旧版本 chunk 以支持审计和重现检索结果。

中文关键词检索对查询与 chunk 正文作 Unicode NFKC、大小写折叠和空白/标点归一化；CJK 连续字符拆成重叠二元词项，拉丁字母/数字按词项匹配。阶段 4 以可复现的词项覆盖率作为关键词分数，并在固定样例集验证，不依赖 PostgreSQL 默认全文分词器对中文的行为。混合排序使用归一化关键词分数 `L` 和归一化余弦分数 `V=clamp((cosine+1)/2,0,1)`：`R=w*L+(1-w)*V`，首期 `w=0.5`；`R` 是排序相关度而非概率或事实可信度。最终并列按素材 UUID 稳定排序。向量服务不可用时允许明确标记的关键词降级，不能伪装为混合结果。

首期可先用精确向量搜索；数据规模和延迟有实际指标后，再建立 HNSW/IVFFlat 索引。结合 PostgreSQL 关键词检索做混合召回；检索结果记录素材、正文片段、相似度和来源。

## 5. 创作与文章

| 表 | 主要字段和关系 |
| --- | --- |
| `creation_rules` | `id`, `name`, `description`, `trigger_type`, `trigger_config`, `material_strategy`, `filters`, `min_material_count`, `min_relevance`, `reference_count`, `batch_count`, `article_type`, `writing_style`, `word_range`, `model_config_id`, `prompt`, `target_account_id`, `enabled` |
| `creation_rule_collection_tasks` | `rule_id`, `collection_task_id`；唯一保存规则与采集任务关系，避免两边重复存 FK |
| `creation_tasks` | `id`, `rule_id`, `mode`, `topic`, `status`, `idempotency_key`, `started_at`, `finished_at`, `error_summary`, `async_job_id`；幂等键唯一 |
| `creation_task_materials` | `creation_task_id`, `material_id`, `relevance_score`, `selection_reason`；记录本次候选/选用素材 |
| `creation_outputs` | `id`, `creation_task_id`, `candidate_titles`, `summary`, `outline`, `keywords`, `cover_suggestion`, `generated_at`, `model_config_id`；保留原始生成结果 |
| `articles` | `id`, `creation_task_id`, `origin_type`, `status`, `current_revision_id`, `created_by`, `created_at`, `updated_at` |
| `article_revisions` | `id`, `article_id`, `version`, `title`, `author`, `keywords`, `summary`, `body_markdown`, `cover_object_id`, `layout_config`, `created_by`, `created_at`；版本不可变 |
| `article_materials` | `article_revision_id`, `material_id`, `reference_order`；该文章版本实际引用素材 |
| `reviews` | `id`, `article_id`, `article_revision_id`, `reviewer_id`, `action`, `checklist`, `comment`, `created_at`；每次审核/复审新建记录；复合外键保证文章与修订一致 |

`creation_task_materials` 表示创作任务检索/采用的素材；`article_materials` 表示文章版本实际引用，两者不可合并。文章关键词以数组或关系表保存，不存逗号拼接字符串。审核项使用稳定 key，例如 `title_accurate`、`facts_traceable`、`sources_valid`、`image_rights_checked`。

## 6. 公众号、发布和指标

| 表 | 主要字段和关系 |
| --- | --- |
| `wechat_accounts` | `id`, `name`, `account_type`, `original_id`, `auth_status`, `authorized_at`, `expires_at`, `capabilities`, `is_default`, `credential_ref` |
| `account_sync_runs` | `id`, `account_id`, `status`, `started_at`, `finished_at`, `item_count`, `error_summary`, `async_job_id` |
| `publish_orders` | `id`, `article_revision_id`, `account_id`, `mode`, `scheduled_at`, `publish_note`, `confirmed_by`, `confirmed_at`, `status`, `created_by`, `created_at` |
| `publish_attempts` | `id`, `publish_order_id`, `attempt_no`, `status`, `external_id`, `response_summary`, `failure_reason`, `started_at`, `finished_at`, `async_job_id` |
| `account_article_metrics` | `id`, `account_id`, `external_article_id`, `article_id`, `captured_at`, `reads`, `likes`, `shares`, `available_metrics`, `raw_payload_redacted` |

规则中的公众号只是默认目标；发布订单中的账号才是本次发布的最终账号。每次调用微信接口新增 `publish_attempts`，不覆盖失败历史。文章状态与每个账号的发布状态分开维护。只能对当前审核通过的版本创建并确认发布订单。

## 7. 异步任务与可靠投递

| 表 | 主要字段 |
| --- | --- |
| `async_jobs` | `id`, `job_type`, `resource_type`, `resource_id`, `celery_task_id`, `status`, `progress`, `retry_count`, `error_summary`, `started_at`, `finished_at`, `idempotency_key` |
| `outbox_events` | `id`, `event_type`, `payload`, `created_at`, `published_at`, `attempt_count` |

领域表（如 `collection_runs`、`creation_tasks`）保存业务状态，`async_jobs` 保存运行状态。业务事务同时写 outbox，由 dispatcher 投递 Celery，避免数据库提交成功但任务消息丢失。Redis/Celery 结果不作为长期业务记录。

## 8. 约束与索引建议

- 对 `creation_tasks.idempotency_key` 建唯一约束；`article_revisions` 对 `(article_id, version)` 建唯一约束。
- 对关联表的复合主键/唯一键、所有外键、状态和时间筛选列建立索引。
- `collection_results` 按 `(run_id, collected_at)`、`store_status` 查询；素材按状态、类型、分类和时间查询。
- `article_materials` 按 `material_id` 建反向索引，支持素材详情列出引用文章。
- 发布订单按状态、计划时间查询；发布尝试按 `(publish_order_id, attempt_no)` 唯一。
- 向量近似索引按真实数据量和检索延迟评估后添加；不要在首期假定规模并过早调参。

## 9. 状态与待确认项

- 采集任务、素材、创作任务和文章状态使用 PRD 中定义的状态；不把“条件不满足”伪装成执行成功。
- “修改后待复审”推荐映射为文章回到“待审核”，旧审核记录仍保留并绑定旧版本；若要作为独立文章状态，需要单独定义状态迁移。
- 发布订单状态至少区分待确认、待发布、发布中、已发布、发布失败、已取消；具体状态迁移由发布模块校验。
- 实现迁移前确定 embedding 模型/维度、实际采集来源可提供的原始内容、微信账号可用权限和排版配置格式。

## 10. 采集增强增量模型（待迁移，任务 3.15）

本节为后续增量，尚未建表或执行迁移；原阶段 3 的表和历史数据保留。详细流程见 [采集增强设计](collection-design.md)，API 见 [增量契约](api-design.md)。

| 对象 | 增量字段/职责与约束 |
| --- | --- |
| `collection_tasks` | 新增 mode、topic、search_config_id、allowed_domains、max_articles、max_pages_per_source、analysis_enabled、analysis_model_config_id、analysis_apply_policy；source 模式至少一个有效来源，topic_search 必须有主题/搜索配置且不绑定来源 ID，服务层事务校验跨表条件 |
| `collection_sources` | web_page 的 config 增加 page_kind=article/list 和链接/下一页规则；旧来源默认 article，不修改现有 rss/web_page 枚举 |
| `search_configs` | 提供方、endpoint、credential_ref、能力声明、限额、enabled、version；独立于新闻来源；与 model_configs 一样更新递增版本并保留脱敏配置快照 |
| `collection_runs` | 新增 task_config_snapshot、frozen_from/to、搜索/模型配置版本、预算/消耗、结束原因及阶段计数；运行中修改任务不改变本次语义 |
| `collection_candidates` | run_id、normalized_url/key、最终 URL、发现标题/日期、筛选状态/原因、result_id；`(run_id, normalized_url_key)` 唯一，明确最终重定向合并关系 |
| `collection_discoveries` | candidate_id、来源 ID（可空）、来源类型、入口/条目 URL、搜索 query/排名/摘要、配置版本及时间；同一候选可有多条发现依据，搜索结果不能伪造人工来源外键 |
| `collection_stage_attempts` | run_id、candidate_id（可空）、stage、scope_key、attempt_no、状态、lease、async_job_id、错误/时间/用量；逻辑执行键及 attempt 唯一，步骤成功后重投复用结果 |
| `collection_content_snapshots` | result_id、原始内容引用、content_markdown、content_hash、hash_normalization_version、提取器版本、title、published_at/date_evidence、created_at；正文快照不可覆盖，重新解析输入/版本变化创建新快照 |
| `material_analysis_runs` | collection snapshot 或 material_revision 二选一作为输入 FK；content_hash、purpose、主题/关键词指纹、model_config_id/version、prompt_version、candidate_revision_ids/指纹、逻辑键、status、结构化输出/校验错误、async_job_id；逻辑键唯一且包含配置/用途/任务输入，历史结果不可冒充当前正文 |
| `material_analysis_attempts` | analysis_run_id、attempt_no、状态、起止时间、脱敏错误、可得 token usage；`(analysis_run_id, attempt_no)` 唯一；超时后保留尝试，未知 usage 为 null |
| `collection_review_decisions` | result_id、输入快照、analysis_run_id（可空）、动作、候选目标修订、原因、操作者、时间；显式人工复核留痕，不将待筛选保留改写成分析成功 |
| `materials` / `material_relations` | 素材新增 metadata_version、字段来源/人工维护标记和 readiness/reason；关系追加 judgment_source、analysis_run_id/人工决定、source/target_revision_id 与 evidence，兼容旧关系这些字段为空 |

分析输入来自采集快照时，通过 collection_results.material_id 和素材首修订来源关系追溯入库产物；采用分析必须验证目标素材当前正文 hash 与输入一致，不能仅用 result_id 判断可用。分析输出与自动/人工采用动作分开存储；采用写字段、metadata_version、来源标记和审计须同事务，标签集合所有写路径均增加元数据版本。旧非空摘要/分类/标签保守标记为已有维护值，不因迁移被模型覆盖。

跨来源完全重复在全库可访问素材范围使用规范化正文 hash 匹配；不改为素材表全局唯一键，以免破坏已有历史数据和事件进展。并发首次创建采用同内容键事务锁或等效领取机制，事务内再次查询；采集结果始终各自保留，关系只是关联，不删除不同来源证据。旧 hash/提取版本不可直接混用，兼容比较需明确规范化版本。

分析关闭或已完成可用判断不等于文章审核通过。素材就绪状态与 usage_status 分离；同一 material_revision 由未就绪变为就绪时，写唯一事件键 `material.ready:<revision_id>` 至 outbox，携带 result/run/task 引用及人工/分析依据。重复来源关联同一修订不会制造第二次新增素材事件；阶段 5 基于原触发窗口和去重约束消费，不要求本阶段存在 creation_rules 表。

迁移顺序：先建 model_configs/search_configs，再扩展任务及运行、候选/快照/分析/人工决定表，最后补外键/索引和校验。采用当前 head 后的新版本；旧任务回填 mode=source、analysis_enabled=false，旧来源 page_kind=article，旧分析状态为 skipped。历史内容不重新抓取，旧修订、来源、审核和引用不更改；旧记录快照仅在显式重新分析时从保留正文建立。升级/应用回退/恢复在独立测试库验证，回退前停用增强模式调度；不能通过改旧迁移或清库实现。

实施补充（3.22–3.27）：0009/0010 修复 analysis scope 长度并保存输入快照/hash、配置/主题上下文和目标修订；0011 为 collection_runs 增加执行租约，为候选增加唯一 result_id 映射并约束阶段 attempt 唯一；0012 保存按来源的 discovery_state。material_ready_events 的 event_key 使用素材/修订组合的 SHA-256（64 字符），同修订仅生成一次就绪事件，与 outbox 同事务写入。尚无阶段 5 消费任务的 material.ready 保持待消费。旧数据升级与应用回退验证见 [增强验收记录](../development/phase-03-enhancement.md)。


## 阶段7直连与发布落地

新增 0018_wechat_accounts / 0019_publish_orders：wechat_accounts 保存不可变 AppID、加密 Secret/token、实际到期点、凭据版本、人工确认与只读探测能力；默认账号部分唯一索引保证最多一个。account_sync_runs 保存运行计数与历史，account_synced_materials 对账号/media_id/图文项序号唯一；creation_rules.target_account_id 补账号外键。

publish_orders 用复合外键绑定文章修订，保存账号、方式/UTC时间、评论参数快照及确认者/时间；同账号同修订最多一个非失败/取消订单。publish_attempts 的 (order_id,attempt_no) 唯一，保留草稿ID、publish_id、阶段、外部结果和核对记录；未知提交不重置为待执行。文章审核状态独立，列表提供各账号订单 publish_summary；单账号成功不掩盖其他失败。完整字段以迁移和 OpenAPI 为准，见 [直连设计](wechat-direct-design.md) 与 [阶段7验收记录](../development/phase-07.md)。


### 0020：微信草稿交付与人工发布登记

`wechat_draft_deliveries` 通过修订/文章复合外键绑定审核版本，关联账号和 async_jobs，保存评论参数快照、运营确认、远端草稿 media_id、独立状态和错误。非 failed/cancelled 的同修订/账号部分唯一索引防重复交付；人工登记保存 operator 来源、操作者/时间、文章链接和非空说明。`wechat_draft_attempts` 的 (delivery_id,attempt_no) 唯一，保留写入阶段、用于核对的私有 expected_payload、media_id、错误、核对者和说明。同步成功要求草稿ID，人工登记要求证据字段。交付/尝试均保留历史，不与 publish_orders/attempts 混用；仅人工登记会将当前版本文章更新为 published。

迁移回退再升级仅在独立测试库验证；业务部署先备份并执行 alembic upgrade head，再重启 API/Worker/Beat/dispatcher。应用回退保留新表，禁止将测试清库步骤用于业务库。


## 0021：运营管理落地

system_settings以key单例保存平台JSON、version、更新者和时间；平台记录默认Asia/Shanghai，以乐观版本更新。notification_preferences以(user_id,category,channel)为主键，保存各类站内偏好和更新时间。notifications以(recipient_id,event_key,channel)唯一，关联所需permission，保存真实事件时间、创建时间和独立read_at；接收者/未读索引支持隔离分页，列表和已读时再次复验当前权限。

account_article_metrics关联账号、可空文章、微信外部msgid、群发日期、采集时间、availability及可空reads/likes/shares。非负校验、不可用状态禁止伪造数值、账号/外部文章/日期唯一；同日显式重采更新快照并保留最新采集时间。人工链接未能与msgid可靠映射时article_id为空，不凭标题强行关联。查询取所选采集区间每账号/外部文章的最近快照；旧快照有明确采集时间，失败另存不可用标识，不能当作实时0值。

0021独立测试库回退至0020后再升级验证；业务库升级前备份，应用回退优先保留数据表而非破坏性downgrade。Beat每30秒从持久业务事实生成最多500条站内通知，唯一键防重；偏好关闭/重新启用依据更新时间避免补发关闭期间历史事件。站内渠道为本期唯一可用adapter，邮件/微信外发明确禁用。

## 阶段9检索与运行交付

0022_search_indexes 为 materials.title 与 material_revisions.content_markdown 增加存储型 search_terms、GIN、当前素材、来源关联及稳定分页复合索引。词项函数执行 NFKC/小写、中文二元词、Latin/数字词，并先去重重复词段；仅当前有效修订参与默认检索。material_chunks 使用1024位二值量化的 HNSW 表达式索引（m=8、ef_construction=32），原1024维向量保留用于余弦重排；ANN 候选是近似结果，不能承诺精确全库 top-k。

空库全量迁移及带历史数据恢复副本的0022→0021→0022验证见阶段9；downgrade只删除本次新增列/索引/函数，正文、素材、引用、审核与交付历史不变。业务库回退优先使用兼容应用，较早业务schema回退使用联合快照恢复到新库/新桶。备份对象清单记录大小、SHA-256和版本ID，恢复工具拒绝覆盖已有桶并逐对象读回校验。运行期不将未知外部写入直接重置为pending。

已投递 outbox 的作业标识表达式索引支持领取前消息丢失的安全恢复；只重投仍pending且超时的原作业，未改变外部未知状态的核对规则。

### 0023：共享向量索引与分块映射

同一模型配置及版本下，material_search_vectors 以原始向量二进制的SHA-256去重，保留1024维向量；material_chunk_search_vectors 将每个原始分块关联到索引向量。原 material_chunks.embedding 全部保留，原分块ID、修订、引用和执行记录不更改。触发器在分块插入/向量及配置更新时同事务维护映射，向量置空或删除分块时移除映射。失去引用的索引向量可保留，检索必须经映射回到当前有效且生成成功的分块，不能把它直接当素材返回。

图索引建立在共享向量上（binary HNSW，m=16、ef_construction=128），防止大量重复向量破坏候选召回。先取得向量候选并以原始余弦排序，再经LATERAL查询关联当前素材，每个修订只保留一个分块。模型配置及版本仍强制隔离。索引向量与映射是可重建的派生结构，回退演练核对原业务记录哈希及重新建立后的映射一致性；联合备份仍包含全部表。
