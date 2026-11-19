import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { PublishPanel } from './PublishPanel'
import { accountsApi, publishingApi, type Account, type PublishOrder } from '../../shared/api/wechat'

vi.mock('../../app/AuthContext', () => ({ useAuth: () => ({ hasPermission: () => true }) }))
vi.mock('../../shared/api/wechat', async original => ({ ...await original<typeof import('../../shared/api/wechat')>(), accountsApi: { list: vi.fn() }, publishingApi: { list: vi.fn(), detail: vi.fn(), attempts: vi.fn(), create: vi.fn(), action: vi.fn(), reconcile: vi.fn() } }))
const api = vi.mocked(publishingApi)
const account: Account = { id: 'a1', name: '测试公众号', app_id: 'wx0123456789abcdef', account_type: 'subscription', status: 'active', credential_version: 1, credential_configured: true, is_default: false, publish_permission_confirmed: true, publish_defaults: { need_open_comment: false, only_fans_can_comment: false }, capabilities: { publish: { available: true, reason: '人工确认及读取探测通过' } }, checked_at: null, authorized_at: '2026-11-19T00:00:00Z', last_synced_at: null, error_code: null }
const row: PublishOrder = { id: 'o1', resource_id: 'o1', article_id: 'article1', article_revision_id: 'rev1', account_id: 'a1', status: 'awaiting_confirmation', mode: 'immediate', scheduled_at: null, publish_note: '', publish_defaults: account.publish_defaults, confirmed_by: null, confirmed_at: null, async_job_id: null, error_code: null, created_at: account.authorized_at, updated_at: account.authorized_at }
beforeEach(() => { vi.clearAllMocks(); window.location.hash = '#/content/articles/article1'; vi.mocked(accountsApi.list).mockResolvedValue({ items: [account], total: 1, page: 1, page_size: 100 }); api.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }); api.detail.mockResolvedValue(row); api.attempts.mockResolvedValue([]) })

it('创建订单之后必须再次明确确认，不自动启动发布', async () => {
  const user = userEvent.setup()
  api.create.mockImplementation(async () => { api.list.mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 20 }); return row })
  api.action.mockResolvedValue({ ...row, status: 'confirmed' })
  render(<PublishPanel articleId="article1" revisionId="rev1" articleStatus="approved" />)
  await user.selectOptions(await screen.findByRole('option', { name: '测试公众号' }).then(option => option.parentElement!), 'a1')
  await user.click(screen.getByRole('button', { name: '创建待确认发布单' }))
  await screen.findByRole('button', { name: '确认按上述账号、版本和时间发布' })
  expect(api.action).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '确认按上述账号、版本和时间发布' }))
  await waitFor(() => expect(api.action).toHaveBeenCalledWith('o1', 'confirm', expect.any(String)))
})

it('结果未知时显示核对入口并隐藏直接重试', async () => {
  const user = userEvent.setup()
  window.location.hash = '#/content/articles/article1?order_id=o1'
  const unknown = { ...row, status: 'unknown', confirmed_by: 'u1', confirmed_at: row.created_at }
  api.list.mockResolvedValue({ items: [unknown], total: 1, page: 1, page_size: 20 })
  api.detail.mockResolvedValue(unknown)
  api.reconcile.mockResolvedValue(unknown)
  render(<PublishPanel articleId="article1" revisionId="rev1" articleStatus="approved" />)
  expect(await screen.findByRole('button', { name: '提交结果核对' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '重试已确认失败的发布单' })).not.toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText('核对方式'), 'not_published')
  await user.type(screen.getByLabelText('核对依据'), '测试后台确认没有发布记录')
  await user.click(screen.getByRole('button', { name: '提交结果核对' }))
  await waitFor(() => expect(api.reconcile).toHaveBeenCalledWith('o1', expect.objectContaining({ outcome: 'not_published', note: '测试后台确认没有发布记录' })))
})
