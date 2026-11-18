/** Verifies collection page URL state, task actions and result->material links (task 3.9). */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { collectionApi } from '../../shared/api/collection'
import { apiRequest, ApiError } from '../../shared/api/client'
import { FeedbackProvider } from '../../shared/components/feedback'
import { CollectionPage } from './CollectionPage'

vi.mock('../../shared/api/client', () => ({
  ApiError: class MockApiError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
    }
  },
  apiRequest: vi.fn(),
}))

vi.mock('../../shared/api/collection', () => ({
  collectionApi: {
    listSources: vi.fn(), createSource: vi.fn(), testSource: vi.fn(),
    listTasks: vi.fn(), createTask: vi.fn(), runTask: vi.fn(),
    pauseTask: vi.fn(), resumeTask: vi.fn(), listRuns: vi.fn(),
    listResults: vi.fn(), materialize: vi.fn(), bulkMaterialize: vi.fn(),
    ignoreResult: vi.fn(), retryParse: vi.fn(),
  },
}))

const mockRequest = vi.mocked(apiRequest)
const api = vi.mocked(collectionApi)
const emptyPage = { items: [], total: 0, page: 1, page_size: 10 }

const task = {
  id: 'task-1', name: '每日采集', status: 'active', keywords: [],
  sources: [{ id: 's1', name: 'RSS 来源' }],
  schedule: { frequency: 'manual', timezone: 'Asia/Shanghai' },
  time_range_days: 7, auto_materialize: false, auto_create: false,
  created_at: '', updated_at: '',
}

const pendingResult = {
  id: 'r1', run_id: 'run-1', title: '固件更新', url: 'https://example.com/1',
  collected_at: '', parse_status: 'parsed', materialize_status: 'pending',
  material_id: null, created_at: '', updated_at: '',
}

const materializedResult = { ...pendingResult, id: 'r2', materialize_status: 'materialized', material_id: 'material-real-id' }

beforeEach(() => {
  vi.clearAllMocks()
  mockRequest.mockImplementation((path: string) => {
    if (String(path).endsWith('/candidates')) return Promise.resolve([])
    if (String(path).startsWith('/collection/config-options')) return Promise.resolve({ searches: [], models: [] })
    if (String(path).startsWith('/collection/sources')) return Promise.resolve(emptyPage)
    if (String(path).startsWith('/collection/tasks')) return Promise.resolve({ ...emptyPage, items: [task], total: 1 })
    if (String(path).startsWith('/collection/runs')) return Promise.resolve(emptyPage)
    if (String(path).startsWith('/collection/results')) return Promise.resolve({ ...emptyPage, items: [pendingResult, materializedResult], total: 2 })
    return Promise.resolve(emptyPage)
  })
})

function renderPage() {
  return render(
    <FeedbackProvider>
      <CollectionPage />
    </FeedbackProvider>,
  )
}

describe('CollectionPage', () => {
  it('restores the sub-view and filters from the URL', async () => {
    window.location.hash = '#/collection?view=results&run_id=run-1&page=2'
    renderPage()
    await waitFor(() => expect(mockRequest).toHaveBeenCalled())
    const resultsCall = mockRequest.mock.calls.find((call) => String(call[0]).startsWith('/collection/results'))
    expect(resultsCall).toBeDefined()
    const url = String(resultsCall?.[0])
    expect(url).toContain('run_id=run-1')
    expect(url).toContain('page=2')
  })

  it('accepts a run task from the task list with real API feedback', async () => {
    window.location.hash = '#/collection?view=tasks'
    renderPage()
    const runButton = await screen.findByRole('button', { name: '立即执行' })
    api.runTask.mockResolvedValue({ async_job_id: 'j1', resource_type: 'collection_run', resource_id: 'run-1', status: 'accepted' })
    await userEvent.setup().click(runButton)
    await waitFor(() => expect(api.runTask).toHaveBeenCalledWith('task-1'))
    expect(await screen.findByText(/任务已受理/)).toBeTruthy()
  })

  it('links a materialized result to the real material detail page', async () => {
    window.location.hash = '#/collection?view=results'
    renderPage()
    const link = await screen.findByRole('button', { name: '查看素材' })
    await userEvent.setup().click(link)
    expect(window.location.hash).toContain('/materials/material-real-id')
  })

  it('shows an API error without faking success', async () => {
    window.location.hash = '#/collection?view=results'
    renderPage()
    const materialize = await screen.findAllByRole('button', { name: '入库' })
    api.materialize.mockRejectedValue(new ApiError(409, 'result_ignored', '该结果已忽略'))
    await userEvent.setup().click(materialize[0])
    expect(await screen.findByText('该结果已忽略')).toBeTruthy()
  })

  it('writes view switches back to the URL', async () => {
    window.location.hash = '#/collection?view=tasks'
    renderPage()
    await userEvent.setup().click(screen.getByRole('button', { name: '执行记录' }))
    expect(window.location.hash).toContain('view=runs')
  })
})
