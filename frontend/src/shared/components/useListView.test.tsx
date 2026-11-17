import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import { useListView } from './useListView'
import { ListStates } from './states'

vi.mock('../api/client', () => ({
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

import { apiRequest } from '../api/client'

const mockRequest = vi.mocked(apiRequest)

interface Row { id: string }

function Probe({ path, page, pageSize }: { path: string; page: number; pageSize: number }) {
  const view = useListView<Row>(path, { page, pageSize })
  return (
    <div>
      <span data-testid="status">{view.status}</span>
      <ListStates status={view.status} error={view.error} onRetry={view.retry} />
    </div>
  )
}

describe('useListView', () => {
  it('maps a non-empty result to ready with data', async () => {
    mockRequest.mockResolvedValueOnce({ items: [{ id: 'a' }], total: 1, page: 1, page_size: 10 })
    render(<Probe path="/users" page={1} pageSize={10} />)
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'))
    expect(mockRequest).toHaveBeenCalledWith('/users?page=1&page_size=10', expect.anything())
  })

  it('maps an empty result to the empty state', async () => {
    mockRequest.mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 10 })
    render(<Probe path="/users" page={1} pageSize={10} />)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('暂无数据'))
  })

  it('maps 403 to the forbidden state', async () => {
    mockRequest.mockRejectedValueOnce(new ApiError(403, 'forbidden', '无权限'))
    render(<Probe path="/users" page={1} pageSize={10} />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('无访问权限'))
    expect(screen.getByTestId('status')).toHaveTextContent('forbidden')
  })

  it('maps other API errors to the error state with the server message', async () => {
    mockRequest.mockRejectedValueOnce(new ApiError(500, 'internal_error', '服务器内部错误'))
    render(<Probe path="/users" page={1} pageSize={10} />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('服务器内部错误'))
  })

  it('retries after a failure', async () => {
    mockRequest.mockRejectedValueOnce(new ApiError(0, 'network_error', '网络请求失败'))
    mockRequest.mockResolvedValueOnce({ items: [{ id: 'a' }], total: 1, page: 1, page_size: 10 })
    render(<Probe path="/users" page={1} pageSize={10} />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('ready'))
    expect(mockRequest).toHaveBeenCalledTimes(2)
  })
})
