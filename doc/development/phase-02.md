# 阶段 2 验收记录（2026-11-17）

对应任务：tasks.md 第 2 组（2.1–2.11）。契约语义决策见 [api-phase-02.md](api-phase-02.md)。

## 验收证据

| 验证项 | 结果 | 证据 |
| --- | --- | --- |
| 数据库迁移 | 通过 | `alembic upgrade head` → `0002_async_execution`；downgrade→upgrade 循环通过；约束测试覆盖幂等键唯一/对象重复登记/job 状态 CHECK |
| 异步受理契约 | 通过 | `GET /async-jobs`（分页/筛选）、`GET /async-jobs/{id}`（属主校验 403）、`POST cancel`（终态 409 `job_not_cancellable`）集成测试通过 |
| Celery/Redis | 通过 | Beat→Redis(6380)→Worker 实测：`system.healthcheck` 任务 pending→running→succeeded（attempts=1，progress=100），outbox 事件确认 dispatched |
| 事务 outbox | 通过 | 业务事务回滚不产生事件；投递失败重试计数+退避；崩溃后重投仅一次业务副作用（claim 语义防重入） |
| 幂等键 | 通过 | 同键同内容返回原结果（真实端点验证）；同键异内容 409 `idempotency_conflict`；并发同键仅一行；过期键可复用 |
| RustFS 文件流 | 通过 | 实测：申请授权→presigned PUT→完成登记→短期下载 URL→内容一致；越权完成 403、未上传 400、授权过期 400、无权下载 403 |
| 审计与脱敏 | 通过 | 成功/拒绝操作均写 operation_logs；password/token/secret/key 类字段在日志中为 `***` |
| 前端轮询/上传 | 通过 | 任务轮询（URL 按任务 ID 恢复、终态停止、网络失败可恢复、卸载清理）；上传组件（授权→直传进度→登记、登记失败可重试）；组件测试 25 passed |
| 测试 | 通过 | 后端 **72 passed**（含真实 Redis/RustFS 集成，均指向 wetchat_test 专用库）；前端 **25 passed**；`pnpm build` 通过 |

## 全套进程实测（2.11 验证）

按 README 启动 uvicorn + worker（-Q async_jobs --pool solo）+ beat 后：

1. 创建 `system.healthcheck` 任务并投递 outbox 事件 → worker 消费执行 →
   `GET /async-jobs/{id}` 返回 `succeeded`（attempts=1）。
2. 通过 API 完成一次真实上传下载（授权→直传→登记→短期下载），内容逐字节一致。

## 已知事项

1. `.env` 曾入库待轮换凭据（见 phase-01.md）；阶段 2 未新增仓库内凭据。
2. Broker 断连恢复依赖 dispatcher 的 beat 周期（5s），断连期间事件保持 pending 且计入 attempts。
3. 业务 handler（采集/创作等）自阶段 3 起接入；`system.healthcheck` 作为流水线冒烟样例保留。
4. Worker 使用 `--pool solo`（Windows 单机验证用）；Linux 生产建议 prefork。
