import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { AccountsPage } from './AccountsPage'
import { accountsApi, type Account } from '../../shared/api/wechat'

const state = vi.hoisted(() => ({ writable: true }))
vi.mock('../../app/AuthContext', () => ({ useAuth: () => ({ hasPermission: (code: string) => code === 'account:write' ? state.writable : true }) }))
vi.mock('../../shared/api/wechat', () => ({ wechatErrorMessage: (code: string) => code, accountsApi: { list: vi.fn(), detail: vi.fn(), bind: vi.fn(), check: vi.fn(), runs: vi.fn() } }))
const api = vi.mocked(accountsApi)
const account: Account = { id: 'a1', name: '测试公众号', app_id: 'wx0123456789abcdef', account_type: 'subscription', status: 'active', credential_version: 1, credential_configured: true, is_default: false, publish_permission_confirmed: false, publish_defaults: { need_open_comment: false, only_fans_can_comment: false }, capabilities: { materials: { available: true, reason: '只读成功' }, publish: { available: false, reason: '尚未确认微信发布接口权限' } }, checked_at: null, authorized_at: '2026-11-19T00:00:00Z', last_synced_at: null, error_code: null }
beforeEach(() => { vi.clearAllMocks(); state.writable = true; api.list.mockResolvedValue({ items: [account], total: 1, page: 1, page_size: 100 }); api.detail.mockResolvedValue(account); api.runs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }) })

it('只读用户查看能力原因，不显示凭据写入入口', async () => {
  state.writable = false
  window.location.hash = '#/accounts?account_id=a1'
  render(<AccountsPage />)
  expect(await screen.findByText(/尚未确认微信发布接口权限/)).toBeInTheDocument()
  expect(screen.getByText(/已配置，不回显/)).toBeInTheDocument()
  expect(screen.queryByText('接入公众号')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '解除绑定' })).not.toBeInTheDocument()
})

it('凭据提交成功后清空密码输入，不把连接校验当作发布', async () => {
  const user = userEvent.setup()
  api.bind.mockResolvedValue(account)
  window.location.hash = '#/accounts'
  render(<AccountsPage />)
  await user.click(screen.getByText('接入公众号'))
  await user.type(screen.getByLabelText('公众号名称'), '测试公众号')
  await user.type(screen.getByLabelText('AppID'), 'wx0123456789abcdef')
  await user.type(screen.getByLabelText('AppSecret'), 'test-only-credential')
  await user.click(screen.getByRole('button', { name: '校验凭据并接入' }))
  await waitFor(() => expect(api.bind).toHaveBeenCalledWith(expect.objectContaining({ publish_permission_confirmed: false })))
  await waitFor(() => expect(screen.getByLabelText('AppSecret')).toHaveValue(''))
})
