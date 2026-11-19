import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { DraftDeliveryPanel } from './DraftDeliveryPanel'
import { accountsApi, draftsApi, type Account, type DraftDelivery } from '../../shared/api/wechat'

vi.mock('../../app/AuthContext', () => ({ useAuth: () => ({ hasPermission: () => true }) }))
vi.mock('../../shared/api/wechat', async original => ({ ...await original<typeof import('../../shared/api/wechat')>(), accountsApi: { list: vi.fn() }, draftsApi: { list: vi.fn(), attempts: vi.fn(), create: vi.fn(), action: vi.fn(), reconcile: vi.fn(), manualPublished: vi.fn() } }))
const api = vi.mocked(draftsApi)
const account: Account = { id: 'a1', name: '个人订阅号', app_id: 'wx0123456789abcdef', account_type: 'subscription', status: 'active', credential_version: 1, credential_configured: true, is_default: false, publish_permission_confirmed: false, publish_defaults: { need_open_comment: false, only_fans_can_comment: false }, capabilities: { drafts: { available: true, reason: '读取通过' }, publish: { available: false, reason: '个人号不可用' } }, checked_at: null, authorized_at: '2026-11-19T00:00:00Z', last_synced_at: null, error_code: null }
const row: DraftDelivery = { id: 'd1', resource_id: 'd1', article_id: 'article1', article_revision_id: 'rev1', account_id: 'a1', status: 'awaiting_manual_publish', note: '', async_job_id: 'job1', remote_media_id: 'media1', error_code: null, confirmed_by: 'u1', confirmed_at: account.authorized_at, publication_source: null, manual_published_by: null, manual_published_at: null, manual_article_url: null, manual_note: null, created_at: account.authorized_at, updated_at: account.authorized_at }
beforeEach(() => { vi.clearAllMocks(); vi.mocked(accountsApi.list).mockResolvedValue({ items: [account], total: 1, page: 1, page_size: 100 }); api.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }); api.attempts.mockResolvedValue([]) })

it('个人号无发布接口权限仍可显式确认同步，成功不自动标记已发布', async () => {
  const user = userEvent.setup(), onPublished = vi.fn()
  api.create.mockImplementation(async () => { api.list.mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 20 }); return row })
  render(<DraftDeliveryPanel articleId="article1" revisionId="rev1" articleStatus="approved" onPublished={onPublished} />)
  await user.selectOptions(await screen.findByLabelText('草稿目标公众号'), 'a1')
  await user.click(screen.getByRole('checkbox', { name: /我已核对当前审核版本/ }))
  await user.click(screen.getByRole('button', { name: '确认同步到微信草稿箱' }))
  expect(await screen.findByRole('heading', { name: '草稿已同步，待微信后台手动发布' })).toBeInTheDocument()
  expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ confirm_sync: true, account_id: 'a1', article_revision_id: 'rev1' }), expect.any(String))
  expect(onPublished).not.toHaveBeenCalled()
  await user.type(screen.getByLabelText('微信文章链接'), 'https://mp.weixin.qq.com/s/fixture')
  await user.type(screen.getByLabelText('人工发布说明'), '已在微信后台发布')
  await user.click(screen.getByRole('checkbox', { name: /我已在微信后台发布/ }))
  api.manualPublished.mockResolvedValue({ ...row, status: 'manual_published', publication_source: 'operator' })
  await user.click(screen.getByRole('button', { name: '登记已手动发布' }))
  await waitFor(() => expect(api.manualPublished).toHaveBeenCalledWith('d1', { content_matches_revision: true, article_url: 'https://mp.weixin.qq.com/s/fixture', note: '已在微信后台发布' }))
  expect(onPublished).toHaveBeenCalled()
})

it('未知结果要求核对，旧版本不显示人工发布登记', async () => {
  const user = userEvent.setup()
  api.list.mockResolvedValue({ items: [{ ...row, status: 'unknown' }], total: 1, page: 1, page_size: 20 })
  render(<DraftDeliveryPanel articleId="article1" revisionId="rev2" articleStatus="approved" />)
  await user.click(await screen.findByRole('button', { name: /同步结果未知/ }))
  expect(screen.queryByRole('button', { name: '重试草稿同步' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '登记已手动发布' })).not.toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText('草稿核对方式'), 'not_synced')
  await user.type(screen.getByLabelText('后台核对依据'), '微信后台逐条核对确认无草稿')
  api.reconcile.mockResolvedValue({ ...row, status: 'failed' })
  await user.click(screen.getByRole('button', { name: '核对草稿结果' }))
  await waitFor(() => expect(api.reconcile).toHaveBeenCalledWith('d1', { outcome: 'not_synced', note: '微信后台逐条核对确认无草稿' }))
})
