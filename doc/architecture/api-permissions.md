# 已实现 API 与权限矩阵

由 `backend/scripts/export_api_catalog.py` 从路由依赖和 OpenAPI 生成。字段及状态码完整快照见 `api-catalog.json`。

| 方法 | 路径 | 会话 | 权限（全部满足） | CSRF | 状态码 |
| --- | --- | --- | --- | --- | --- |
| GET | /health | public | — | 否 | 200 |
| GET | /ready | public | — | 否 | 200, 503 |
| POST | /api/v1/auth/login | public | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/auth/logout | session | — | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/auth/me | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/articles | session | article:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/articles | session | article:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/articles/preview | session | article:read | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/articles/models | session | article:write | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/articles/{article_id} | session | article:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/articles/{article_id}/revisions | session | article:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/articles/{article_id}/revisions/{revision_id} | session | article:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/articles/{article_id}/revisions | session | article:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/articles/{article_id}/ai-actions | session | article:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/articles/{article_id}/submit-review | session | article:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/reviews/queue | session | article:review | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/article-revisions/{revision_id}/reviews | session | article:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/article-revisions/{revision_id}/reviews | session | article:review | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/async-jobs | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/async-jobs/{job_id} | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/async-jobs/{job_id}/cancel | session | — | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/files/{object_id}/image | session | article:read | 否 | 307, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/files/upload-grants | session | — | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/files/upload-grants/{grant_id}/complete | session | — | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/files/{object_id}/download-grant | session | — | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/config-options | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/sources | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/sources | session | collection:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/sources/{source_id} | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/collection/sources/{source_id} | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/collection/sources/{source_id} | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/sources/{source_id}/test | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/tasks | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/tasks | session | collection:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/tasks/{task_id} | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/collection/tasks/{task_id} | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/collection/tasks/{task_id} | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/tasks/{task_id}/pause | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/tasks/{task_id}/resume | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/tasks/{task_id}/run | session | collection:run | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/runs | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/runs/{run_id} | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/results | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/results/{result_id} | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/results/{result_id}/materialize | session | collection:run | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/results/bulk-materialize | session | collection:run | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/results/{result_id}/ignore | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/results/{result_id}/retry-parse | session | collection:run | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/analysis | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/analysis/{analysis_id} | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/analysis/{analysis_id}/retry | session | collection:run | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/analysis/{analysis_id}/apply | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/results/{result_id}/retain | session | collection:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/collection/runs/{run_id}/candidates | session | collection:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/collection/runs/{run_id}/retry | session | collection:run | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/creation-rules | session | creation:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/creation-rules | session | creation:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/creation-rules/{rule_id} | session | creation:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PUT | /api/v1/creation-rules/{rule_id} | session | creation:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/creation-rules/{rule_id} | session | creation:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/creation-rules/{rule_id} | session | creation:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/creation-rules/{rule_id}/run | session | creation:write | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/creation-tasks | session | creation:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/creation-tasks | session | creation:write | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/creation-tasks/models | session | creation:write | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/creation-tasks/target-accounts | session | creation:write | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/creation-tasks/{task_id} | session | creation:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/creation-tasks/{task_id}/outputs | session | creation:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/creation-tasks/{task_id}/cancel | session | creation:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/creation-tasks/{task_id}/retry | session | creation:write | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/creation-tasks/{task_id}/regenerate | session | creation:write | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/search | session | material:search | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/{material_id}/analysis | session | material:write | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/{material_id}/embedding-rebuild | session | settings:write | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials | session | material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials | session | material:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/from-link | session | material:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/from-upload | session | material:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials/favorites | session | material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/bulk | session | material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials/categories | session | material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/categories | session | material:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/materials/categories/{category_id} | session | material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/materials/categories/{category_id} | session | material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials/tags | session | material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/materials/tags | session | material:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/materials/tags/{tag_id} | session | material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/materials/tags/{tag_id} | session | material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials/{material_id} | session | material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/materials/{material_id} | session | material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/materials/{material_id} | session | material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials/{material_id}/revisions | session | material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials/{material_id}/relations | session | material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/materials/{material_id}/articles | session | article:read, material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PUT | /api/v1/materials/{material_id}/favorite | session | material:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/materials/{material_id}/favorite | session | material:write | 是 | 200, 204, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/search-configs/{config_id} | session | settings:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/search-configs | session | settings:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/search-configs | session | settings:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/search-configs/{config_id} | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/search-configs/{config_id}/test | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/model-configs/{config_id} | session | settings:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/model-configs/{config_id} | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/model-configs | session | settings:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/model-configs | session | settings:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/model-configs/{config_id}/test | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/users | session | user:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/users | session | user:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/users/{user_id} | session | user:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/users/{user_id} | session | user:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/wechat-accounts | session | account:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-accounts | session | account:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-accounts/callback | public | — | 否 | 200, 400, 401, 403, 404, 409, 410, 422, 503 |
| GET | /api/v1/wechat-accounts/callback | public | — | 否 | 200, 400, 401, 403, 404, 409, 410, 422, 503 |
| POST | /api/v1/wechat-accounts/authorization | public | — | 否 | 200, 400, 401, 403, 404, 409, 410, 422, 503 |
| GET | /api/v1/wechat-accounts/authorization | public | — | 否 | 200, 400, 401, 403, 404, 409, 410, 422, 503 |
| GET | /api/v1/wechat-accounts/{account_id} | session | account:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-accounts/{account_id}/check | session | account:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PUT | /api/v1/wechat-accounts/{account_id}/credentials | session | account:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PATCH | /api/v1/wechat-accounts/{account_id} | session | account:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PUT | /api/v1/wechat-accounts/{account_id}/default | session | account:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| DELETE | /api/v1/wechat-accounts/{account_id} | session | account:write | 是 | 204, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-accounts/{account_id}/sync | session | account:write | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/wechat-accounts/{account_id}/sync-runs | session | account:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/publish-orders | session | publish:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/publish-orders | session | publish:confirm | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/publish-orders/{order_id} | session | publish:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/publish-orders/{order_id}/confirm | session | publish:confirm | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/publish-orders/{order_id}/cancel | session | publish:confirm | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/publish-orders/{order_id}/retry | session | publish:execute | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/publish-orders/{order_id}/attempts | session | publish:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/publish-orders/{order_id}/reconcile | session | publish:execute | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/wechat-draft-deliveries | session | publish:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-draft-deliveries | session | publish:confirm | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/wechat-draft-deliveries/{delivery_id} | session | publish:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/wechat-draft-deliveries/{delivery_id}/attempts | session | publish:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-draft-deliveries/{delivery_id}/retry | session | publish:confirm | 是 | 202, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-draft-deliveries/{delivery_id}/cancel | session | publish:confirm | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-draft-deliveries/{delivery_id}/reconcile | session | publish:confirm | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/wechat-draft-deliveries/{delivery_id}/manual-published | session | publish:confirm | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/roles | session | role:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/roles | session | role:write | 是 | 201, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/roles/{role_id} | session | role:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PUT | /api/v1/roles/{role_id}/permissions | session | role:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/settings/runtime | session | operation_log:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/settings/runtime/recover-stale | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/settings/outbox | session | operation_log:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/settings/outbox/{event_id}/retry | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/settings/permissions | session | role:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/platform | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/settings/platform | session | settings:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PUT | /api/v1/settings/platform | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/dashboard | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/analytics/{kind} | session | analytics:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/analytics/{kind}/export | session | analytics:export, analytics:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/analytics/accounts/{account_id}/collect-metrics | session | account:write, analytics:read | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/notifications/channels | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/notifications/preferences | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| PUT | /api/v1/notifications/preferences | session | — | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/notifications | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/notifications/refresh | session | — | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/notifications/{notification_id}/read | session | — | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/settings/operation-logs | session | operation_log:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/settings/jobs | session | operation_log:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/settings/integrations | session | settings:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/settings/integrations/storage/test | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/settings/integrations/embedding/test | session | settings:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/assistance/models | session | article:read, material:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/assistance/topics | session | article:read, creation:write, material:read | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/assistance/runs/{run_id} | session | — | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/assistance/materials/{material_id}/relations | session | material:read, material:search | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/assistance/materials/{material_id}/relations | session | material:read, material:search | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/assistance/relations/{suggestion_id}/ignore | session | material:read, material:search, material:write | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/assistance/search | session | material:read, material:search | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| POST | /api/v1/assistance/articles/{article_id}/quality | session | article:read, material:read | 是 | 200, 400, 401, 403, 404, 409, 422, 503 |
| GET | /api/v1/assistance/analytics/reuse | session | account:read, analytics:read, article:read, material:read, publish:read | 否 | 200, 400, 401, 403, 404, 409, 422, 503 |

“—”表示路由依赖未声明额外权限码，不代表没有动态权限或对象级检查。GET /api/v1/assistance/runs/{run_id} 仅限本人，按记录类型额外要求：topic 为 creation:write、material:read、article:read；relation 和 search 为 material:read、material:search；quality 为 article:read、material:read。异步作业限本人创建，上传授权与完成限本人，文件下载限上传者或已取得对应资源访问权。公开 OAuth 占位路径固定返回410，直连模式不会执行授权副作用。图片访问返回307短期重定向，报表导出为text/csv。
