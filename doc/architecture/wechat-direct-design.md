# 自有公众号直连（阶段 7）

2026-11-19，用户明确选择自有公众号直连。复用公众号自身 AppID/AppSecret，调用固定微信 API 域名，不采用第三方平台代授权或网页用户 OAuth。旧设计的 `/authorization`、`/callback` 不再是本模式的入口；本期不开放 OAuth 或消息推送回调，以轮询查询发布结果。旧回调请求明确返回 410，不绑定账号，伪造/过期/重放 OAuth 参数均无副作用。

## 账号与凭据

`POST /wechat-accounts` 接收名称、账号类型、AppID、只写 AppSecret、运营在微信后台确认的发布权限标识与默认发布参数。连接校验成功才绑定；名称/类型为人工资料，不宣称微信自动核验。AppID 绑定后不可改变。AppSecret 与缓存 token 以 APP_SECRET_KEY 派生的 Fernet 密钥加密，查询只返回已配置状态；更换 APP_SECRET_KEY 前需迁移或重新录入账号凭据。

`POST /{id}/check` 以 stable_token(force_refresh=false) 校验凭据，并用只读素材/草稿/已发布列表探测可用性。只读成功不能证明发布提交接口已授权：发布条件必须包含运营在微信后台的明确确认、草稿及发布读取探测可用；界面说明依据，执行时微信拒绝仍记录为失败并更新账号能力。不以测试发布探测权限。访问来源 IP 需加入对应账号的 API 白名单。

`PUT /{id}/credentials` 为重新接入，只写新 Secret，成功后递增凭据版本；旧网络校验不能覆盖新版本或恢复已解绑账号。`PATCH /{id}` 维护名称、权限确认和默认发布参数；`PUT /{id}/default` 串行切换默认账号，部分唯一索引兜底。`DELETE /{id}` 为解绑，保留账号、同步与发布历史，阻止新操作。`POST /{id}/sync` 返回 202/job/resource；`GET /{id}/sync-runs` 查询历史。

同步首版范围为永久图文素材（news），有界分页，按账号/media_id/图文项序号关联，正文转 Markdown 入库为待筛选。非图文二进制同步不在本期首版 adapter 范围，界面明确说明。重复同步不重复入库；正文更新保留首个同步快照，不覆写已有人工素材，可另行采集新版本。

## 可控发布

`POST /publish-orders` 绑定已人工批准的当前修订、账号、方式、UTC 定时时间、备注；创建只保存订单。`POST /{id}/confirm` 独立记录运营确认并复验批准/账号能力，立即模式才创建作业；定时模式由 Beat 到期复验后创建作业。`POST /{id}/cancel` 仅取消未执行订单。`POST /{id}/retry` 只重试已确认失败订单，重新复验后新增 attempt，不覆盖历史。创建、确认、重试、同步均支持同用户/动作作用域的 Idempotency-Key，异内容返回 409。

发布状态：`awaiting_confirmation → confirmed → preparing → submitting → publishing → succeeded/failed`；提交网络中断或进程失联为 `unknown`。`publish_id` 仅表示微信受理，`freepublish/get` 返回成功后才标记业务成功。`preparing` 失败可恢复；`submitting/unknown` 不得自动重发。dispatcher/Worker 重入只处理同一尝试一次；超时或重启保留提交阶段。

`POST /{id}/reconcile` 优先用已知 publish_id 查询；无 publish_id 时，具备执行权限者须填写核对依据，确认未发布才转失败并允许人工重试，确认已发布需记录外部文章 ID 与结果证据。`GET /{id}/attempts` 保留每次尝试的阶段、时间和脱敏结果。未知状态不能直接重试；失败重试仍绑定原批准版本。修改版本后旧订单阻断，不自动替换版本。各账号订单状态独立；文章只在当前修订有成功订单时显示已发布，列表仍显示每单结果。

网络调用不持有数据库长写事务。执行前在文章/账号/订单锁下复验并持久化阶段；提交前再次复验，只有当前 attempt 仍有效才发送。已开始外部提交的订单拒绝取消。generic job 取消和 stale 回收不能令发布订单变回可直接发送，状态由发布服务控制。

进入 submitting/publishing/unknown 后，文章保存返回 409 publication_in_progress，防止最终复验与外部请求之间出现新版。confirmed/preparing 期间仍允许编辑，随后执行复验会阻断旧版本订单；结果明确后按文章状态处理编辑。

封面必须是已登记的 PNG/JPEG，上传为微信永久图片；正文中受控图片读取 RustFS 后上传微信图文图片接口。任意外部图片不在服务端自动抓取，发布准备明确失败并提示先上传替换，避免静默丢图。转换复用阶段 6 的安全 Markdown/排版 HTML。微信字段长度与正文大小超限明确失败，不截断用户已确认内容。

## 个人订阅号草稿交付（用户已确认）

采用独立 `/wechat-draft-deliveries` 资源。创建时运营明确确认同步当前已审版本，事务创建交付/job/outbox；Worker复验后转换图片及正文，持久化待写入payload，再调用 draft/add。状态 pending/preparing/syncing/unknown/awaiting_manual_publish/manual_published/failed/cancelled。synced不是published，交付不会调用freepublish接口。账号只须连接正常且草稿读取可用，写入是否支持以实际返回为准。

同修订/账号至多一条有效交付，attempt按序保存。syncing/unknown阻止并发保存文章；准备中改版会阻断写入。成功后可继续编辑，但旧交付不授权新版本且不能登记新版发布。未知写入有界读取400组草稿，以标题、封面、正文纯文本及图片URL匹配，完整覆盖全部记录且唯一匹配才恢复media_id；超过400组或查询不完整拒绝自动匹配；无匹配保持未知，人工记录确认未同步后方可重试。返回异常不记录原始凭据或未脱敏响应。

人工发布登记要求当前批准版本、微信文章HTTPS链接、非空说明和内容一致声明；记录operator来源、确认人/时间，不调用发布API或声称微信验证成功。账号发布权限不是草稿交付前置条件。旧API发布保留给具备权限的账号，个人账号页面优先草稿流程。

官方草稿接口：[新增草稿](https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html)，摘要限120字；创建后可在微信公众平台草稿箱管理。实际写入验证采用标记用途样例，成功后保留待用户查看，不能自动发表。

## 官方依据（2026-11-19 核对）

- [稳定版 token](https://developers.weixin.qq.com/doc/service/api/base/api_getstableaccesstoken.html)：POST `/cgi-bin/stable_token`，普通模式不会强制刷新。
- [发布能力](https://developers.weixin.qq.com/doc/subscription/guide/product/publish.html)：submit/get/batchget 为不同动作。
- [提交发布](https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_submit.html)：返回任务标识，后续查询状态；0 成功、1 发布中、2/3/4 失败、5/6 已发布后删除/封禁。
- [发布列表](https://developers.weixin.qq.com/doc/subscription/api/public/api_freepublish_batchget.html)：只读探测及结果核对依据。
- [永久图片](https://developers.weixin.qq.com/doc/subscription/api/material/permanent/api_addmaterial.html)：封面为永久 media_id，正文图片使用 uploadimg URL。

测试使用隔离 PostgreSQL 和确定性微信 adapter，不发真实文章。真实接入另记 AppID 脱敏摘要、时间、IP 白名单和账号实际权限；缺少凭据时如实记录未验收。真实发布按 AGENT.md 另取明确授权。
