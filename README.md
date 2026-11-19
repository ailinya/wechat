# 智媒助手

微信公众号智能内容运营平台：采集 → 素材 → 创作 → 审核 → 发布 → 统计。
实施路线与行为规格见 `openspec/changes/project-development-roadmap/`，阶段验收记录见 `doc/development/`。

## 本地运行

### 1. 依赖服务（PostgreSQL + pgvector、Redis、RustFS）

```bash
cp .env.example .env      # 填写真实凭据；.env 已被 .gitignore 忽略，不得提交
docker compose up -d
docker compose ps         # 三个服务均应显示 healthy
```

凭据只写入被忽略的根目录 `.env`，仓库仅保留 `.env.example`。
宿主机 5432/6379/9000/9001 被占用时，在 `.env` 中改 `*_PORT` 映射到其他宿主端口
（容器内端口不变），并同步更新 `DATABASE_URL`。

### 2. 后端（FastAPI + SQLAlchemy + Alembic）

```bash
cd backend
uv sync                                   # 创建 .venv 并安装依赖
# Windows 无 uv 时可用：python -m pip install uv && python -m uv sync

export DATABASE_URL=postgresql+psycopg://wetchat:<密码>@127.0.0.1:5432/wetchat
export APP_SECRET_KEY=<至少 32 个字符的随机串>

uv run alembic upgrade head               # 空库迁移
uv run wetchat-create-admin --account admin --name 管理员 --password '<强密码>'
uv run uvicorn app.asgi:app --reload --port 8000
```

- 健康检查：`GET http://127.0.0.1:8000/health` → `{"status":"ok"}`
- 缺少必要配置（如 `APP_SECRET_KEY`）时启动即报清晰错误，不会带堆栈或密钥。
- 初始管理员密码无默认值：必须用 `--password` 或 `WETCHAT_ADMIN_PASSWORD` 传入。

### 3. 前端（React + Vite）

```bash
cd frontend
pnpm install
pnpm dev                                  # http://127.0.0.1:5173，/api 代理到 127.0.0.1:8000
```

后端不在 8000 端口时：`VITE_API_TARGET=http://127.0.0.1:<端口> pnpm dev`。
端口被其他项目占用时：`VITE_PORT=5174 pnpm dev`（配置固定端口并绑定 127.0.0.1，被占用即报错）。

### 4. 异步执行进程（Celery Worker / Beat，任务 2.3+）

任务状态保存在 PostgreSQL（async_jobs），Redis 只作 broker；任务通过事务性
outbox（outbox_events）投递，Beat 内置 dispatcher 与 stale-reaper：

```bash
# Worker（消费 async_jobs 队列）
cd backend && uv run celery -A app.modules.async_execution.celery_app:celery_app worker -Q async_jobs -l info --pool solo

# Beat（每 5 秒 dispatch outbox；每 5 分钟回收僵尸任务）
cd backend && uv run celery -A app.modules.async_execution.celery_app:celery_app beat -l info
```

需要的环境变量：`DATABASE_URL`、`APP_SECRET_KEY`、`REDIS_URL`、`RUSTFS_ENDPOINT`、
`RUSTFS_ACCESS_KEY`、`RUSTFS_SECRET_KEY`（均见 `.env.example`）。
任务查询/取消契约见 `doc/development/api-phase-02.md`。

## 测试

| 层 | 命令 | 说明 |
| --- | --- | --- |
| 后端单元/契约 | `cd backend && uv run pytest` | 无需数据库；数据库用例自动跳过 |
| 后端集成 | `TEST_DATABASE_URL=postgresql+psycopg://.../wetchat_test uv run pytest` | 指向**专用测试库**（如本地 wetchat_test），自动重建 schema，可重复执行；不会连接生产服务 |
| 前端组件 | `cd frontend && pnpm test` | Vitest + Testing Library（jsdom） |
| 浏览器端到端 | `pnpm e2e`（仓库根目录） | Playwright；未登录守卫等纯前端用例无需后端；登录用例需 `E2E_BACKEND_URL=http://127.0.0.1:8000 E2E_ADMIN_PASSWORD=...`。默认用系统 Edge（`E2E_BROWSER` 可改），前端固定跑在 5174（`VITE_PORT`），避免与本机其他项目的 5173 冲突 |

## 目录

自有公众号直连、账号配置、发布确认与故障核对见 [阶段7运行及验收记录](doc/development/phase-07.md)。真实账号连接与私有草稿读写已有证据；个人订阅号官方 API 发布权限不可用，内部 fixture 成功不代表真实发布成功。

```
backend/    FastAPI 应用（api/routes → schemas → services → repositories）、alembic 迁移
frontend/   React 应用（app/ 壳层、features/ 模块、shared/ 公共）
tests/e2e/  Playwright 浏览器端到端测试
doc/        开发文档（traceability、阶段验收、性能口径）
openspec/   行为规格与实施路线
```


个人订阅号支持“编辑→人工审核→确认同步微信草稿箱→公众号后台手动发布”，同步成功不会标记已发布；后台发布后可登记微信文章链接，显示人工登记来源。真实测试草稿写入及读回已验证。部署与账号限制见 [阶段7验收](doc/development/phase-07.md)，业务库需升级到0020并重启API/Worker/Beat。

阶段8已接入真实业务工作台、六类统计与安全CSV导出、平台信息/用户角色/接口配置、站内通知偏好及日志/任务监控。微信指标无权限或未采集显示不可用，草稿与人工登记分开统计。部署需升级到0021并重启API/Worker/Beat；操作和验证见 [阶段8验收](doc/development/phase-08.md)。

阶段9部署与验收见 [运行手册](doc/deployment/runbook.md)、[集成记录](doc/development/phase-09.md) 和 [交付清单](doc/development/release-checklist.md)。正式部署使用 `deploy/compose.yml` 与 `deploy/.env.example`，迁移到0022；运行恢复位于系统设置的任务监控。当前年规模性能验收仍在执行，首版最终交付以清单实际状态为准。
