# 智媒助手数据库设计

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
| `model_configs` | `id`, `provider`, `model_name`, `endpoint`, `credential_ref`, `purpose`, `parameters`, `enabled`；`purpose` 区分生成与 embedding |
| `system_settings` | `key`, `value`, `updated_by`, `updated_at`；不得存未加密密钥 |
| `notification_preferences` | `user_id`, `event_type`, `channel`, `enabled` |
| `notifications` | `id`, `user_id`, `event_type`, `content`, `read_at`, `created_at` |
| `operation_logs` | `id`, `user_id`, `module`, `action`, `target_type`, `target_id`, `result`, `detail_redacted`, `created_at` |

## 4. 采集与素材

| 表 | 主要字段和关系 |
| --- | --- |
| `collection_sources` | `id`, `name`, `type`, `base_url`, `enabled`, `config`；密钥不放普通配置 |
| `collection_tasks` | `id`, `name`, `keywords`, `scope`, `time_range`, `schedule_cron`, `timezone`, `status`, `auto_store`, `auto_create_enabled`, `created_by` |
| `collection_task_sources` | `task_id`, `source_id`；一个任务可选多个来源 |
| `collection_runs` | `id`, `task_id`, `async_job_id`, `status`, `started_at`, `finished_at`, `total_count`, `success_count`, `failed_count`, `stored_count`, `error_summary` |
| `collection_results` | `id`, `run_id`, `source_id`, `title`, `summary`, `original_url`, `published_at`, `collected_at`, `raw_content`, `raw_object_id`, `parse_status`, `dedup_status`, `store_status`, `matched_material_id`, `error_summary` |
| `materials` | `id`, `title`, `summary`, `type`, `origin_type`, `category_id`, `status`, `current_revision_id`, `created_at`, `updated_at` |
| `material_revisions` | `id`, `material_id`, `version`, `body_markdown`, `content_hash`, `created_from_result_id`, `created_at`；正文历史不可覆盖 |
| `material_relations` | `source_material_id`, `target_material_id`, `relation_type`；区分 `duplicate_of`、`update_of`、`related_to` |
| `material_categories` | `id`, `name`, `parent_id`, `sort_order` |
| `tags` / `material_tags` | 标签定义和素材多对多关系 |
| `stored_objects` | `id`, `object_key`, `file_name`, `mime_type`, `size_bytes`, `checksum`, `created_at` |
| `material_files` | `material_id`, `stored_object_id`, `role`；关联原始附件或素材图片 |
| `material_chunks` | `id`, `material_revision_id`, `chunk_index`, `content`, `content_hash`, `embedding`, `embedding_model`, `created_at` |

采集结果始终保留；自动或人工入库通过 `matched_material_id` 关联素材。重复项关联已有素材；同事件新进展创建新素材，通过 `material_relations` 关联，不覆盖旧正文。采集结果支持未入库、已入库、忽略和解析失败等状态。

素材状态遵循 PRD：待筛选、待使用、已使用、部分使用、已归档、重复素材。正文存 PostgreSQL 的 `TEXT`；原始附件和图片只存 RustFS，PostgreSQL 保存对象键、元数据与关联。

### pgvector 约定

`material_chunks.embedding` 使用 pgvector。首次迁移前必须确定 embedding 模型及向量维度 `D`，字段类型为 `vector(D)`；不同维度不能混在同一向量列。换模型或维度时使用新列/新表并重建向量。正文修订创建新 chunk，保留旧版本 chunk 以支持审计和重现检索结果。

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
| `reviews` | `id`, `article_revision_id`, `reviewer_id`, `action`, `checklist`, `comment`, `created_at`；每次审核/复审新建记录 |

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

