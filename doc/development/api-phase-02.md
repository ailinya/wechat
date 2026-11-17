# 阶段 2 接口契约：异步任务与文件（任务 2.2）

机器可读契约以 `/openapi.json` 为准（tags: `async-jobs`、`files`）；本文记录语义决策，
前端类型已由 `backend/scripts/generate_api_types.py` 重新生成。

## 异步任务（/api/v1/async-jobs）

| 端点 | 语义 |
| --- | --- |
| `GET /async-jobs` | 当前用户任务分页列表，筛选 `job_type`/`status`，按 created_at 稳定倒序 |
| `GET /async-jobs/{job_id}` | 单任务状态；仅创建人可查（403/404）；`status=pending/running` 即“未就绪” |
| `POST /async-jobs/{job_id}/cancel` | 仅创建人；`pending/running` → `cancelled`；已终态 → 409 `job_not_cancellable`（取消与完成竞争时只有一个一致终态） |

后台动作受理（采集执行、创作启动等，自 2.3 起接入）返回 **HTTP 202**，响应体为
`AsyncJobAccepted`：`{async_job_id, resource_type, resource_id, status="accepted"}`。
受理失败（校验/事务回滚）不返回 202，也不产生孤立后台动作。

## 文件（/api/v1/files）

| 端点 | 语义 | 状态 |
| --- | --- | --- |
| `POST /files/upload-grants` | 申请限定对象键/大小/类型/有效期的上传授权，不暴露长期凭据 | 契约已定，501 至任务 2.6 |
| `POST /files/upload-grants/{id}/complete` | 后端校验申请人/授权/对象后登记；重复完成返回同一文件标识（幂等恢复）；过期/不符 → 400 `grant_expired`/`object_mismatch`；越权 → 403 | 同上 |
| `POST /files/{object_id}/download-grant` | 校验资源访问权后签发短期下载地址 | 同上 |

`upload_grants.token_hash` 只存授权凭据哈希；`stored_objects (bucket, object_key)` 唯一，
重复完成登记不会重复建记录（约束由迁移 0002 保证）。

## 幂等键（任务 2.5 实现）

- 副作用请求可携带 `Idempotency-Key` 头（≤128 字符）；作用域由服务端按端点固定。
- 持久化于 `idempotency_keys`，唯一约束 `(scope, user_id, key)`：同用户同作用域下键唯一，
  不同用户可用同一键。
- 同键同内容（请求指纹 sha256 一致）→ 返回原业务结果/原任务标识；
  同键不同内容 → 409 `idempotency_conflict`（示例已在 OpenAPI：`responses.idempotency_conflict_response()`）。
- 并发同键请求只创建一个业务对象（约束 + 事务保证，2.5 验证）。

## 实现说明

- `NotImplementedError` 由统一错误处理转为 **501 `not_implemented`**，用于“契约已定、实现待后续任务”的端点，
  不与真实失败混淆。
- `async_jobs.created_by` 记录发起人，为任务查询/取消提供属主校验；任务状态列 `status`（运行态）
  与业务产物状态解耦，重启后仍可查询（迁移 0002）。
