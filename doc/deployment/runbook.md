# 首版部署与恢复运行手册

适用 Linux Docker Engine + Compose v2；Windows Docker Desktop 的独立验收结果见阶段 9。工作目录为仓库根目录。API、Worker、Beat、dispatcher 共用同一后端镜像与密钥；前端使用 Nginx 托管构建产物。所有宿主端口绑定 loopback，由宿主入口代理提供 HTTPS。只运行一个 Beat；dispatcher 的领取事务允许多实例，但默认一实例。

## 首次部署

1. 将 `deploy/.env.example` 复制到仓库外 `/opt/wetchat/secrets/runtime.env`，限制为运维用户可读。分别生成独立数据库密码、应用密钥、存储密钥和初始管理员密码，替换所有 `CHANGE_ME`。数据库 URL 中的密码必须与 `POSTGRES_PASSWORD` 一致，特殊字符须 URL 编码；可使用十六进制随机串避免编码问题。设置绝对 `APP_ENV_FILE`，按需注入模型服务配置。正式镜像必须用 `APP_TARGET=runtime`、`APP_ENV=production`，不得启用 `ACCEPTANCE_FIXTURE`。
2. 保管 `APP_SECRET_KEY` 的独立加密副本：已保存的微信 Secret/token 依赖它解密，恢复数据库时必须使用原密钥。模型 key、微信 Secret 和备份均不提交 Git。初始化密码仅创建不存在的管理员，不在普通重启时重置；首次登录后更换并从初始化环境移除。
3. 为数据库、Redis 和对象存储卷准备足够持久空间。Compose 默认命名卷，迁移时应在同一项目名下保留。为 50 万素材/250 万 1024 维向量预留正文、向量、索引、WAL 和备份空间，不能仅按原文大小配置容量。

配置样例固定了本次验证的依赖镜像 digest；更新依赖时应另行验证迁移与备份兼容性，再替换 digest。应用镜像构建完成后同样记录 digest，便于按同一版本回退。

以下 Bash 函数使每条命令使用同一项目与环境；不要混用根目录开发 Compose：

```bash
dc() { docker compose --env-file /opt/wetchat/secrets/runtime.env -f deploy/compose.yml "$@"; }
dc build api web
dc up -d --no-build
dc ps
curl -fsS http://127.0.0.1:55179/health
curl -fsS http://127.0.0.1:55179/ready
```

`migrate` 在依赖就绪后升级 Alembic head、创建桶并按需初始化管理员，成功退出后才启动应用进程。初始化失败时先检查 `dc logs migrate`，不要绕过失败的迁移直接启动 Worker。升级版本为 `0023_distinct_search_vectors`。API `/ready` 为 200 且数据库、Broker、存储各项就绪后才导入流量。

公网域名入口代理转发到 `127.0.0.1:55179`；文件域名代理到 `127.0.0.1:59000`，必须保留 Host、路径和签名查询串。将 `RUSTFS_PUBLIC_ENDPOINT` 设置为实际文件 HTTPS 域名，内部仍用 `http://rustfs:9000`，浏览器不能访问 Docker 服务名。配置 `RUSTFS_CORS_ALLOWED_ORIGINS` 为实际前端 Origin（多个 Origin 用英文逗号分隔），Compose 将其注入 RustFS。RustFS 默认值为空，不会返回通用 CORS 头，必须确认浏览器预检及签名 PUT/GET 成功。仅修改 API 的环境不能生效，变更此值需重建 RustFS 容器并保留原数据卷。公网使用 TLS 和 `SESSION_COOKIE_SECURE=true`；loopback HTTP 验收环境明确设为 false。TLS 证书与公网 DNS 是站点运维配置，容器验收不声明这些已上线。

自有公众号在账号页录入 AppID/Secret，并将**后端实际服务器的出口公网 IP**加入微信白名单。白名单不能使用前端访问者的 IP。个人订阅号使用编辑、人工审核、确认同步草稿、公众号后台手动发布；真实同步证据和权限限制见 `phase-07.md`。模型和微信权限检测须用目标账号实际配置，模拟适配器不能替代生产连通性检查。

## 升级与应用回退

升级前停止入口写请求，等待运行中任务结束，停止 API/Worker/Beat/dispatcher，执行下节联合备份，记录部署镜像 digest 与数据库版本。预先构建并保留上一版镜像，不使用可变 tag 作为唯一回退依据。

```bash
dc stop api worker beat dispatcher
dc build api web
dc up -d --no-build --force-recreate migrate
dc up -d --no-build api worker beat dispatcher web
curl -fsS http://127.0.0.1:55179/ready
```

同一 schema head 内优先只切回兼容旧镜像；就绪检查严格核对镜像所带迁移版本，跨 head 回退需在停写窗口降到旧镜像对应版本。0023 的派生索引映射可移除重建，原始分块向量全部保留；降至0022时会恢复旧全分块索引，可能耗时。`head→0021→head` 演练核对业务历史哈希及重建映射。新检索代码依赖0023，不能在其运行时降 schema。更早业务迁移有删除历史表的 downgrade，禁止把降库当作常规回退；不兼容时恢复成新库/新桶，校验后切换连接配置。切回旧镜像时仍保留原 `APP_SECRET_KEY`。

## 故障处理

`/health` 只检查进程存活，故障时也可为 200；`/ready` 对数据库迁移、Redis、RustFS 给出分项结果，依赖故障返回 503。日志为 JSON，用 `request_id`、`job_id`、资源 ID 关联请求和任务，不输出凭据；API 的 `Server-Timing` 用于服务端耗时测量。

在“系统设置→任务监控”检查卡住任务与消息投递。`回收超时任务` 只结束超时执行；恢复后的业务任务需在对应页面确认重试。失败 outbox 只有在原作业仍 pending 时才可恢复，复用原作业与事件。微信 `submitting/syncing` 中断可能已写入远端，回收后转 `unknown`，必须先查询或人工核对远端，禁止直接重发。近期运行中任务不会被无条件重置。确认 Worker 长时间无心跳时再回收；默认超时 30 分钟，须大于单个任务可接受耗时。

消息已投递但数据库故障导致 Worker 未领取时，超时恢复复用原事件和原 pending 作业重新投递；原子领取阻止重复执行。

Redis 故障时业务受理事务和 outbox 保留在数据库；独立 dispatcher 在 Redis 恢复后继续投递。Worker 重启不依赖 Celery 短期结果，状态从 PostgreSQL 读取。模型超时重试只补未完成槽位，已生成文章不重复创建。数据库恢复后连接池重建可用连接。RustFS 不可用时保留业务错误记录，存储恢复后从对应业务页面继续；不能手工把状态改成成功。

## 联合备份与恢复

在维护窗口阻断写入，等待在途作业结束，停止 API/Worker/Beat/dispatcher（仅 stop API 无法保证 Worker 不再写）。备份点必须包含同一业务时刻的数据库与对象；保留原应用密钥的独立加密副本。以下示例目录由运行容器用户 UID 10001 可写，备份不放在静态资源目录。

```bash
dc stop api worker beat dispatcher
mkdir -p /opt/wetchat/backups/release-001/objects
sudo chown -R 10001:10001 /opt/wetchat/backups/release-001
dc exec -T postgres pg_dump -U wetchat -d wetchat -Fc --no-owner --no-acl > /opt/wetchat/backups/release-001/database.dump
dc run --rm --no-deps -v /opt/wetchat/backups/release-001/objects:/snapshot api python -m app.commands.object_snapshot backup --directory /snapshot
sha256sum /opt/wetchat/backups/release-001/database.dump > /opt/wetchat/backups/release-001/database.sha256
dc start api worker beat dispatcher
```

对象清单包含键、大小、Content-Type、版本 ID 和 SHA-256。当前恢复保留业务时点的现存对象内容，不恢复已删除对象的全部 S3 历史版本；引用正文及审核历史由数据库完整保留。将备份加密并复制到另一故障域，定期按以下步骤恢复验证。

恢复使用**新数据库、新桶**，不会覆盖当前业务库。先核对备份数据库 SHA-256；目标库须为空，目标桶须不存在。以下使用固定示例名称，已有目标须换新名称，不能清空旧目标以重试：

```bash
dc exec -T postgres createdb -U wetchat wetchat_restore_001
dc exec -T postgres pg_restore -U wetchat -d wetchat_restore_001 --no-owner --no-acl --exit-on-error < /opt/wetchat/backups/release-001/database.dump
dc run --rm --no-deps -v /opt/wetchat/backups/release-001/objects:/snapshot:ro api python -m app.commands.object_snapshot restore --directory /snapshot --target-bucket attachments-restore-001
dc exec -T postgres psql -U wetchat -d wetchat_restore_001 -c "UPDATE stored_objects SET bucket='attachments-restore-001' WHERE bucket='attachments';"
dc exec -T postgres psql -U wetchat -d wetchat_restore_001 -c "UPDATE upload_grants SET bucket='attachments-restore-001' WHERE bucket='attachments'; UPDATE upload_grants SET expires_at=LEAST(expires_at,now()) WHERE completed_at IS NULL;"
```

对象工具在恢复前校验清单路径、大小和哈希，上传后再逐对象读回校验。桶切换同时更新文件记录与上传授权；未完成上传需重新申请，已完成上传的登记重放必须返回原文件。将恢复环境 `DATABASE_URL` 指向新库、`RUSTFS_BUCKET` 指向新桶，并保留原 `APP_SECRET_KEY`；以只读验证环境启动 API，核对全表行数/内容、孤儿引用、附件下载、历史素材引用、审核与草稿交付链。确认恢复点后再切换正式连接，启动单个 Beat 与 Worker。未知外部写入先核对远端，不因恢复备份重放发布。

## 可重复验收

`backend/scripts/prepare_acceptance.py` 只生成随机测试凭据，不读取真实 `.env`。按 `deploy/compose.yml` + `deploy/compose.acceptance.yml` 启动 `wetchat-acceptance`，完整工作流、故障、备份、迁移脚本位于 `backend/scripts/verify_release_*.py`，证据位于 `doc/development/release-evidence/`。这些脚本有隔离项目和数据库检查，只适用于验收环境，不能直接对业务库执行。

`verify_release_runtime.py` 额外构建正式 runtime target，在独立项目上验证空库部署、登录、健康、静态前端、进程重启与测试端点缺席，结束后停止该探针栈并保留其持久卷。验收数据和备份位于忽略的 `.acceptance/`，不提交凭据或真实备份。
