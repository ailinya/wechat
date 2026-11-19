import { apiRequest } from './client'
import type { Page } from './articles'
import type { DraftDeliveryOut, DraftAttemptOut, DraftDeliveryIn, DraftReconcileIn, ManualPublicationIn } from './types'

export type DraftDelivery = DraftDeliveryOut
export type DraftAttempt = DraftAttemptOut
export const draftLabels: Record<string, string> = { pending: '等待同步', preparing: '准备草稿内容', syncing: '正在同步微信', unknown: '同步结果未知，须核对', awaiting_manual_publish: '草稿已同步，待微信后台手动发布', manual_published: '已发布（人工登记）', failed: '草稿同步失败', cancelled: '已取消', synced: '草稿同步完成' }
export const draftsApi = {
  list: (articleId: string, page = 1) => apiRequest<Page<DraftDelivery>>(`/wechat-draft-deliveries?article_id=${encodeURIComponent(articleId)}&page=${page}&page_size=20`),
  create: (body: DraftDeliveryIn, key: string) => apiRequest<DraftDelivery>('/wechat-draft-deliveries', { method: 'POST', body, headers: { 'Idempotency-Key': key } }),
  action: (id: string, action: 'retry' | 'cancel', key: string) => apiRequest<DraftDelivery>(`/wechat-draft-deliveries/${id}/${action}`, { method: 'POST', headers: { 'Idempotency-Key': key } }),
  attempts: (id: string) => apiRequest<DraftAttempt[]>(`/wechat-draft-deliveries/${id}/attempts`),
  reconcile: (id: string, body: DraftReconcileIn) => apiRequest<DraftDelivery>(`/wechat-draft-deliveries/${id}/reconcile`, { method: 'POST', body }),
  manualPublished: (id: string, body: ManualPublicationIn) => apiRequest<DraftDelivery>(`/wechat-draft-deliveries/${id}/manual-published`, { method: 'POST', body }),
}

export interface Account { id: string; name: string; app_id: string; account_type: string; status: string; is_default: boolean; credential_configured: boolean; credential_version: number; publish_permission_confirmed: boolean; publish_defaults: { need_open_comment: boolean; only_fans_can_comment: boolean }; capabilities: Record<string, { available: boolean; reason: string }>; checked_at: string | null; authorized_at: string; last_synced_at: string | null; error_code: string | null }
export interface SyncRun { id: string; account_id: string; async_job_id: string; status: string; imported_count: number; reused_count: number; error_code: string | null; created_at: string; finished_at: string | null }
export interface PublishOrder { id: string; resource_id: string; article_id: string; article_revision_id: string; account_id: string; mode: string; scheduled_at: string | null; publish_note: string; publish_defaults: Account['publish_defaults']; status: string; confirmed_by: string | null; confirmed_at: string | null; async_job_id: string | null; error_code: string | null; created_at: string; updated_at: string }
export interface PublishAttempt { id: string; order_id: string; attempt_no: number; status: string; draft_media_id: string | null; publish_id: string | null; article_id_external: string | null; article_url: string | null; error_code: string | null; result: Record<string, unknown>; started_at: string; finished_at: string | null; reconciled_by: string | null; reconciliation_note: string | null }
export const accountsApi = {
  list: (page = 1) => apiRequest<Page<Account>>(`/wechat-accounts?page=${page}&page_size=100`),
  detail: (id: string) => apiRequest<Account>(`/wechat-accounts/${id}`),
  bind: (body: object) => apiRequest<Account>('/wechat-accounts', { method: 'POST', body }),
  check: (id: string) => apiRequest<Account>(`/wechat-accounts/${id}/check`, { method: 'POST' }),
  reconnect: (id: string, app_secret: string) => apiRequest<Account>(`/wechat-accounts/${id}/credentials`, { method: 'PUT', body: { app_secret } }),
  update: (id: string, body: object) => apiRequest<Account>(`/wechat-accounts/${id}`, { method: 'PATCH', body }),
  setDefault: (id: string) => apiRequest<Account>(`/wechat-accounts/${id}/default`, { method: 'PUT' }),
  unbind: (id: string) => apiRequest<void>(`/wechat-accounts/${id}`, { method: 'DELETE' }),
  sync: (id: string, key: string) => apiRequest<{ resource_id: string; async_job_id: string; status: string }>(`/wechat-accounts/${id}/sync`, { method: 'POST', headers: { 'Idempotency-Key': key } }),
  runs: (id: string, page = 1) => apiRequest<Page<SyncRun>>(`/wechat-accounts/${id}/sync-runs?page=${page}&page_size=20`),
}
export const publishingApi = {
  detail: (id: string) => apiRequest<PublishOrder>(`/publish-orders/${id}`),
  list: (articleId?: string, page = 1, accountId?: string) => apiRequest<Page<PublishOrder>>(`/publish-orders?${new URLSearchParams({ page: String(page), page_size: '20', ...(articleId ? { article_id: articleId } : {}), ...(accountId ? { account_id: accountId } : {}) })}`),
  create: (body: object, key: string) => apiRequest<PublishOrder>('/publish-orders', { method: 'POST', body, headers: { 'Idempotency-Key': key } }),
  action: (id: string, action: 'confirm' | 'cancel' | 'retry', key: string) => apiRequest<PublishOrder>(`/publish-orders/${id}/${action}`, { method: 'POST', headers: { 'Idempotency-Key': key } }),
  attempts: (id: string) => apiRequest<PublishAttempt[]>(`/publish-orders/${id}/attempts`),
  reconcile: (id: string, body: object) => apiRequest<PublishOrder>(`/publish-orders/${id}/reconcile`, { method: 'POST', body }),
}
export const publishLabels: Record<string, string> = { awaiting_confirmation: '待运营确认', confirmed: '已确认／等待执行', preparing: '准备发布内容', submitting: '正在提交微信', publishing: '微信处理中', unknown: '结果未知，须核对', succeeded: '已发布', failed: '发布失败', cancelled: '已取消' }

export function wechatErrorMessage(code: string): string {
  const draftReasons: Record<string, string> = { draft_worker_interrupted: '同步进程失联，须先核对微信草稿，不能直接重试', draft_preparation_interrupted: '草稿准备中断，请检查后重试', manually_confirmed_not_synced: '运营已在微信后台核对并确认未同步', draft_delivery_in_progress: '草稿正在同步或等待核对，请先处理结果再编辑', draft_scan_incomplete: '草稿记录未能全部查询，请到微信后台人工核对', draft_not_found: '未找到匹配草稿，请到微信后台核对后记录依据', draft_match_ambiguous: '存在多个匹配草稿，请到微信后台人工核对', draft_delivery_exists: '此账号已有该版本的有效草稿交付，请查看原记录', draft_internal_error: '草稿同步未完成，请检查任务记录；未知结果须先核对' }
  if (draftReasons[code]) return draftReasons[code]
  const reasons: Record<string, string> = { manually_confirmed_not_published: '运营已核对并确认未发布', wechat_unreachable: '微信响应不可用，请检查网络；已提交的内容须先核对结果', wechat_40164: '服务器出口 IP 未加入微信 API 白名单', wechat_40125: '公众号 AppSecret 无效', wechat_40001: '公众号调用凭据已失效，请重新检测', wechat_48001: '公众号没有该接口权限', wechat_publish_2: '微信原创校验未通过', wechat_publish_3: '微信发布失败', wechat_publish_4: '微信平台审核未通过', sync_limit_reached: '本次同步达到400组上限，已保存部分结果', worker_interrupted: '执行进程失联，须核对微信结果', preparation_interrupted: '发布内容准备中断，可检查后重试', cover_required: '缺少封面图片，请保存新版本并重新审核', external_image_not_uploaded: '正文外部图片须先上传替换并重新审核', account_unavailable: '账号连接异常或已解绑', account_permission_missing: '账号接口权限不足', revision_conflict: '文章已更新，须重新审核和创建发布单', wechat_content_too_long: '内容超出微信字段长度限制，请修改后重新审核', account_changed: '账号配置已变化，请重新检查', article_not_approved: '当前文章版本未获人工批准' }
  return reasons[code] || `操作未完成，请检查配置后重试（${code}）`
}
