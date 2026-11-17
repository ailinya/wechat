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

```
backend/    FastAPI 应用（api/routes → schemas → services → repositories）、alembic 迁移
frontend/   React 应用（app/ 壳层、features/ 模块、shared/ 公共）
tests/e2e/  Playwright 浏览器端到端测试
doc/        开发文档（traceability、阶段验收、性能口径）
openspec/   行为规格与实施路线
```

