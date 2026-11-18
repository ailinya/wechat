/** Verifies material library URL state, markdown body, favorites and empty references (task 3.10). */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { materialsApi } from '../../shared/api/materials'
import { apiRequest } from '../../shared/api/client'
import { FeedbackProvider } from '../../shared/components/feedback'
import { MaterialsPage } from './MaterialsPage'

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

vi.mock('../../shared/api/materials', () => ({
  materialsApi: {
    list: vi.fn(), create: vi.fn(), createFromLink: vi.fn(), createFromUpload: vi.fn(),
    get: vi.fn(), update: vi.fn(), remove: vi.fn(), bulk: vi.fn(),
    listCategories: vi.fn(), createCategory: vi.fn(), listTags: vi.fn(),
    createTag: vi.fn(), renameTag: vi.fn(), deleteTag: vi.fn(),
    favorite: vi.fn(), unfavorite: vi.fn(),
  },
}))

vi.mock('../dashboard/FileUploadDemo', () => ({
  FileUploadDemo: () => <div>上传组件占位</div>,
}))

const mockRequest = vi.mocked(apiRequest)
const api = vi.mocked(materialsApi)

const material = {
  id: 'm1', title: '固件 2.1 发布说明', origin: 'collection', usage_status: 'ready_to_use',
  current_revision_id: 'rev-1', tags: [{ id: 't1', name: '行业动态' }],
  created_at: '', updated_at: '',
}

const detail = {
  ...material,
  current_revision: {
    id: 'rev-1', material_id: 'm1', revision_no: 3,
    content_markdown: '**固件 2.1** 修复了中文输入问题……', file_ids: [], created_at: '',
  },
  favorite_count: 2, favorited_by_me: false,
}

const emptyPage = { items: [], total: 0, page: 1, page_size: 10 }

beforeEach(() => {
  vi.clearAllMocks()
  mockRequest.mockResolvedValue({ ...emptyPage, items: [material], total: 1 } as never)
  api.get.mockResolvedValue(detail as never)
  api.favorite.mockResolvedValue(undefined as never)
})

function renderPage() {
  return render(
    <FeedbackProvider>
      <MaterialsPage />
    </FeedbackProvider>,
  )
}

describe('MaterialsPage', () => {
  it('restores filters from the URL', async () => {
    window.location.hash = '#/materials?usage_status=ready_to_use&keyword=固件&page=2'
    renderPage()
    await waitFor(() => expect(mockRequest).toHaveBeenCalled())
    const url = decodeURIComponent(String(mockRequest.mock.calls[0][0]))
    expect(url).toContain('usage_status=ready_to_use')
    expect(url).toContain('keyword=固件')
    expect(url).toContain('page=2')
  })

  it('shows the current revision Markdown body and Chinese source', async () => {
    window.location.hash = '#/materials?material_id=m1'
    renderPage()
    const detailBtn = await screen.findByRole('button', { name: '详情' })
    await userEvent.setup().click(detailBtn)
    expect(await screen.findByText(/修复了中文输入问题/)).toBeTruthy()
    expect(screen.getByText(/来源：采集/)).toBeTruthy()
    expect(screen.getByText(/当前修订 v3/)).toBeTruthy()
  })

  it('shows a real empty state for article references', async () => {
    window.location.hash = '#/materials?material_id=m1'
    renderPage()
    await userEvent.setup().click(await screen.findByRole('button', { name: '详情' }))
    expect(await screen.findByText(/引用关系将在智能创作能力接入后显示/)).toBeTruthy()
  })

  it('favorites a material through the API with feedback', async () => {
    window.location.hash = '#/materials'
    renderPage()
    const favoriteBtn = await screen.findByRole('button', { name: '收藏' })
    await userEvent.setup().click(favoriteBtn)
    await waitFor(() => expect(api.favorite).toHaveBeenCalledWith('m1'))
    expect(await screen.findByText('已收藏')).toBeTruthy()
  })

  it('writes filter changes back to the URL', async () => {
    window.location.hash = '#/materials'
    renderPage()
    const select = await screen.findByLabelText('状态筛选')
    await userEvent.setup().selectOptions(select, 'used')
    expect(window.location.hash).toContain('usage_status=used')
  })
})
