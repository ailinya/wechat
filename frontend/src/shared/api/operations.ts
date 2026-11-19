import { apiRequest } from './client'
import type { Page } from './articles'
import type { RuntimeOut, RuntimeRecoveryOut, OutboxOut, OutboxRetryOut, ConnectionOut, DashboardOut, IntegrationOut, MonitoredJobOut, NotificationChannels, NotificationOut, OperationLogOut, PlatformIn, PlatformOut, PlatformPublic, PreferenceIn, PreferenceOut, ReportOut, UserOut, UserCreate, UserUpdate, RoleOut, RoleCreate, PermissionCode, PermissionOut } from './types'

export const reportKinds = { collection: '采集分析', materials: '素材与复用', creation: '创作分析', reviews: '人工审核', publishing: '发布与草稿', accounts: '公众号运营指标' }
export type ReportKind = keyof typeof reportKinds
export const operationsApi = {
  runtime: () => apiRequest<RuntimeOut>('/settings/runtime'),
  recoverStale: () => apiRequest<RuntimeRecoveryOut>('/settings/runtime/recover-stale', { method: 'POST' }),
  outbox: (page = 1) => apiRequest<Page<OutboxOut>>(`/settings/outbox?page=${page}&page_size=20`),
  retryOutbox: (id: string) => apiRequest<OutboxRetryOut>(`/settings/outbox/${id}/retry`, { method: 'POST' }),
  permissions: () => apiRequest<PermissionOut[]>('/settings/permissions'),
  platform: () => apiRequest<PlatformOut>('/settings/platform'),
  publicPlatform: () => apiRequest<PlatformPublic>('/platform'),
  savePlatform: (body: PlatformIn) => apiRequest<PlatformOut>('/settings/platform', { method: 'PUT', body }),
  dashboard: () => apiRequest<DashboardOut>('/dashboard'),
  report: (kind: ReportKind, query: URLSearchParams) => apiRequest<ReportOut>(`/analytics/${kind}?${query}`),
  export: async (kind: ReportKind, query: URLSearchParams) => {
    const response = await fetch(`/api/v1/analytics/${kind}/export?${query}`, { credentials: 'include' })
    if (!response.ok) { const result = await response.json(); throw new Error(result.error?.message || '导出失败') }
    const blob = await response.blob(), url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `${kind}.csv`; a.click(); URL.revokeObjectURL(url)
  },
  notifications: (query = new URLSearchParams()) => apiRequest<Page<NotificationOut>>(`/notifications?${query}`),
  refreshNotifications: () => apiRequest<{ delivered: number }>('/notifications/refresh', { method: 'POST' }),
  readNotification: (id: string) => apiRequest<NotificationOut>(`/notifications/${id}/read`, { method: 'POST' }),
  preferences: () => apiRequest<PreferenceOut[]>('/notifications/preferences'),
  preference: (body: PreferenceIn) => apiRequest<PreferenceOut[]>('/notifications/preferences', { method: 'PUT', body }),
  channels: () => apiRequest<NotificationChannels>('/notifications/channels'),
  logs: (query: URLSearchParams) => apiRequest<Page<OperationLogOut>>(`/settings/operation-logs?${query}`),
  jobs: (query: URLSearchParams) => apiRequest<Page<MonitoredJobOut>>(`/settings/jobs?${query}`),
  integrations: () => apiRequest<IntegrationOut[]>('/settings/integrations'),
  storageTest: () => apiRequest<ConnectionOut>('/settings/integrations/storage/test', { method: 'POST' }),
  embeddingTest: () => apiRequest<ConnectionOut>('/settings/integrations/embedding/test', { method: 'POST' }),
  metrics: (account: string, day: string) => apiRequest<ConnectionOut>(`/analytics/accounts/${account}/collect-metrics`, { method: 'POST', body: { metric_date: day } }),
  users: (query: URLSearchParams) => apiRequest<Page<UserOut>>(`/users?${query}`),
  createUser: (body: UserCreate) => apiRequest<UserOut>('/users', { method: 'POST', body }),
  updateUser: (id: string, body: UserUpdate) => apiRequest<UserOut>(`/users/${id}`, { method: 'PATCH', body }),
  roles: (page = 1) => apiRequest<Page<RoleOut>>(`/roles?page=${page}&page_size=100`),
  allRoles: async () => {
    const items: RoleOut[] = []; let page = 1
    while (true) { const result = await apiRequest<Page<RoleOut>>(`/roles?page=${page}&page_size=100`); items.push(...result.items); if (items.length >= result.total || !result.items.length) return items; page += 1 }
  },
  createRole: (body: RoleCreate) => apiRequest<RoleOut>('/roles', { method: 'POST', body }),
  updateRole: (id: string, permission_codes: PermissionCode[]) => apiRequest<RoleOut>(`/roles/${id}/permissions`, { method: 'PUT', body: { permission_codes } }),
}

export const operationStatus: Record<string, string> = { synced: '草稿同步完成', pending: '等待执行', running: '执行中', succeeded: '成功', failed: '失败', cancelled: '已取消', insufficient: '条件不足', partial: '部分成功', approve: '审核通过', return: '退回修改', reject: '审核驳回', approved: '审核通过', draft: '草稿', pending_review: '待审核', published: '已发布', available: '可用', unavailable: '不可用', manual_published: '已发布（人工登记）', awaiting_manual_publish: '草稿已同步，待手动发布', unknown: '结果未知，须核对' }
export const operationSource: Record<string, string> = { api_publish: '接口发布单', draft_sync: '草稿交付', operator: '人工发布登记', wechat_metrics: '微信指标', human_review: '人工审核', collection: '采集执行', automatic: '自动创作', material: '素材创作', topic: '主题创作' }
