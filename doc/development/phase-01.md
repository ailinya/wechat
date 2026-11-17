# 阶段 1 验收记录（2026-11-17）

对应任务：`openspec/changes/project-development-roadmap/tasks.md` 第 1 组（1.1–1.10）。

## 验收证据

| 验证项 | 结果 | 证据 |
| --- | --- | --- |
| 依赖服务健康 | 通过 | `docker compose up -d` 后 `docker compose ps`：postgres / redis / rustfs 均 healthy |
| 空库迁移 | 通过 | `alembic upgrade head`：`Running upgrade -> 0001_access_control` |
| 初始管理员 | 通过 | `wetchat-create-admin` 输出 `admin account 'admin' created; admin role granted`；无默认密码（缺 `--password`/`WETCHAT_ADMIN_PASSWORD` 时命令以退出码 2 拒绝） |
| 登录/会话 | 通过 | `POST /api/v1/auth/login` 200（返回权限集）；错误密码 401；注销后凭据失效（集成测试） |
| 健康检查 | 通过 | `GET /health` → `{"status":"ok"}` |
| 缺失配置报错 | 通过 | 缺 `APP_SECRET_KEY` 时启动报清晰错误，不含堆栈/密钥（`test_app.py`） |
| 后端测试 | 通过 | `TEST_DATABASE_URL` 指向专用 `wetchat_test` 库：**33 passed**（认证、权限矩阵、CSRF、分页契约）；未设置时数据库用例自动跳过，永不连接生产服务 |
| 前端组件测试 | 通过 | Vitest + Testing Library：**15 passed**（四类状态、分页控件、useListView 状态映射与重试、演示页 URL 恢复筛选/分页） |
| 浏览器端到端 | 通过 | Playwright（`tests/e2e/`）：未登录守卫与登录页用例通过，真实登录用例设置 `E2E_BACKEND_URL` 后执行；见下方"端到端"一节 |
| 前端构建 | 通过 | `pnpm build`（tsc -b + vite build）成功 |
| 共享列表约定 | 通过 | `shared/components/`（states / DataTable / Pagination / useListView / useUrlQuery / feedback）；演示页 `/#/dashboard/components-demo` 展示加载/空/失败/无权限四态，筛选与分页写入 URL |

## 端到端（登录→导航→退出）

```bash
pnpm exec playwright test   # 根目录
E2E_BACKEND_URL=http://127.0.0.1:8000 E2E_ADMIN_PASSWORD=... pnpm exec playwright test
```

本地验收时使用空库迁移出的 `wetchat` 库 + 验证管理员执行通过。

## 交付物

- 根目录 `docker-compose.yml`（PostgreSQL+pgvector / Redis / RustFS，凭据经 `.env` 注入）
- 根目录 `.env.example`；`.env` 已被 `.gitignore` 忽略并从 git 索引移除
- `README.md`：本地运行、迁移、管理员创建、测试命令、端口冲突说明
- `doc/development/performance-baseline.md`：预期素材规模/并发与性能测量口径

## 已知事项与风险

1. **`.env` 曾被提交**：本次已执行 `git rm --cached .env` 并补全 `.gitignore`，但历史提交中仍含凭据。
   建议：轮换 `POSTGRES_PASSWORD`、`RUSTFS_ACCESS_KEY/SECRET_KEY` 与 `APP_SECRET_KEY`；
   如仓库已推送共享，需评估清理历史。
2. 后端 ASGI 入口由 `app.main:app` 改为 `app.asgi:app`（`main.py` 保持纯工厂，导入不再要求运行时配置）。
3. 性能口径已定义但尚无业务数据流，实测数字从阶段 2/3 起回填（见 performance-baseline.md）。
