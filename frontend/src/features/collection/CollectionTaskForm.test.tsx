import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { apiRequest } from '../../shared/api/client'
import { FeedbackProvider } from '../../shared/components/feedback'
import { CollectionTaskForm } from './CollectionTaskForm'
vi.mock('../../shared/api/client', () => ({ apiRequest: vi.fn() }))

it('submits a topic search without source ids and with selected limits', async () => {
  const request = vi.mocked(apiRequest)
  request.mockImplementation(async path => path === '/collection/config-options' ? { searches: [{ id: 'search', name: '新闻搜索' }], models: [] } : {})
  const saved = vi.fn()
  render(<FeedbackProvider><CollectionTaskForm sources={[]} onSaved={saved} onCancel={() => {}} /></FeedbackProvider>)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('任务名称'), '行业日报')
  await user.selectOptions(screen.getByLabelText('采集模式'), 'topic_search')
  await user.type(screen.getByLabelText('主题'), '人工智能')
  await user.selectOptions(screen.getByLabelText('搜索配置'), 'search')
  await user.click(screen.getByRole('button', { name: '新建任务' }))
  await waitFor(() => expect(saved).toHaveBeenCalled())
  const call = request.mock.calls.find(call => call[1]?.method === 'POST')
  expect(call?.[1]?.body).toMatchObject({ mode: 'topic_search', topic: '人工智能', source_ids: [], search_config_id: 'search', max_fetch: 20, analysis: { enabled: false } })
})
