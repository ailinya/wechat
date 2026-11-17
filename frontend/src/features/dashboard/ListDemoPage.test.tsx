/** Verifies URL-backed filters/pagination on the demo page (task 1.8 verification). */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '../../shared/api/client'
import { ListDemoPage } from './ListDemoPage'

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

const mockRequest = vi.mocked(apiRequest)

const pagePayload = {
  items: [{ id: 'x', account: 'a', name: '甲', status: 'active', created_at: '', updated_at: '' }],
  total: 11,
  page: 1,
  page_size: 10,
}

describe('ListDemoPage URL state', () => {
  beforeEach(() => {
    mockRequest.mockResolvedValue(pagePayload)
  })

  it('restores filters and pagination from the URL', async () => {
    window.location.hash = '#/dashboard/components-demo?page=3&page_size=10&keyword=user01&status=active'
    render(<ListDemoPage />)
    await waitFor(() => expect(mockRequest).toHaveBeenCalled())
    const url = String(mockRequest.mock.calls[0][0])
    expect(url).toContain('page=3')
    expect(url).toContain('page_size=10')
    expect(url).toContain('keyword=user01')
    expect(url).toContain('status=active')
  })

  it('writes pagination changes back to the URL', async () => {
    window.location.hash = '#/dashboard/components-demo'
    render(<ListDemoPage />)
    const next = await screen.findByText('下一页')
    await userEvent.setup().click(next)
    expect(window.location.hash).toContain('page=2')
  })

  it('resets the page when a filter is applied', async () => {
    window.location.hash = '#/dashboard/components-demo?page=2'
    render(<ListDemoPage />)
    const input = screen.getByLabelText('关键词筛选')
    await userEvent.setup().type(input, 'user02')
    await userEvent.setup().click(screen.getByRole('button', { name: '筛选' }))
    expect(window.location.hash).toContain('keyword=user02')
    expect(window.location.hash).not.toContain('page=2')
  })
})
