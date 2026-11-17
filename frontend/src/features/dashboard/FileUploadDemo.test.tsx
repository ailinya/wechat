/** Tests for the upload flow component (task 2.9). */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { filesApi, uploadToPresignedUrl } from '../../shared/api/files'
import { FileUploadDemo } from './FileUploadDemo'

vi.mock('../../shared/api/files', () => ({
  filesApi: { requestGrant: vi.fn(), completeUpload: vi.fn() },
  uploadToPresignedUrl: vi.fn(),
}))

const mockGrant = vi.mocked(filesApi.requestGrant)
const mockComplete = vi.mocked(filesApi.completeUpload)
const mockPut = vi.mocked(uploadToPresignedUrl)

const grant = {
  id: 'grant-1', bucket: 'attachments', object_key: '2026/11/x.txt',
  content_type: 'text/plain', size_bytes: 5, expires_at: '2026-11-17T08:15:00Z',
  upload_url: 'http://rustfs.local/put?sig=1',
}

const stored = {
  id: 'object-1', bucket: 'attachments', object_key: '2026/11/x.txt',
  size_bytes: 5, content_type: 'text/plain', sha256: 'a'.repeat(64), created_at: '2026-11-17T08:05:00Z',
}

beforeEach(() => {
  mockGrant.mockReset()
  mockComplete.mockReset()
  mockPut.mockReset()
  // jsdom lacks crypto.subtle.digest for Blob; stub the digest path by
  // having completeUpload return regardless (the component passes its hash).
})

function chooseFile() {
  const file = new File(['hello'], 'hello.txt', { type: 'text/plain' })
  const input = screen.getByLabelText('选择文件') as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [file] })
  input.dispatchEvent(new Event('change', { bubbles: true }))
  return file
}

describe('FileUploadDemo', () => {
  it('runs grant -> upload -> register and shows the stored object', async () => {
    mockGrant.mockResolvedValue(grant)
    mockPut.mockImplementation(async (_url, _file, onProgress) => {
      onProgress?.(50)
      onProgress?.(100)
    })
    mockComplete.mockResolvedValue(stored)

    render(<FileUploadDemo />)
    chooseFile()
    await userEvent.setup().click(screen.getByRole('button', { name: '上传' }))

    await waitFor(() => expect(screen.getByText('登记完成')).toBeInTheDocument())
    expect(mockGrant).toHaveBeenCalledWith(expect.objectContaining({ filename: 'hello.txt' }))
    expect(mockPut).toHaveBeenCalledWith('http://rustfs.local/put?sig=1', expect.anything(), expect.anything())
    expect(screen.getByText(/文件已登记：object-1/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows progress while uploading', async () => {
    let resolvePut: () => void = () => {}
    mockGrant.mockResolvedValue(grant)
    mockPut.mockImplementation(
      (_url, _file, onProgress) =>
        new Promise<void>((resolve) => {
          resolvePut = () => {
            onProgress?.(100)
            resolve()
          }
        }),
    )
    mockComplete.mockResolvedValue(stored)

    render(<FileUploadDemo />)
    chooseFile()
    await userEvent.setup().click(screen.getByRole('button', { name: '上传' }))
    await waitFor(() => expect(screen.getByText('直传中…')).toBeInTheDocument())

    act(() => resolvePut())
    await waitFor(() => expect(screen.getByText('登记完成')).toBeInTheDocument())
  })

  it('shows the failure reason and retries registration after a lost response', async () => {
    mockGrant.mockResolvedValue(grant)
    mockPut.mockResolvedValue(undefined)
    mockComplete
      .mockRejectedValueOnce(new Error('登记响应丢失'))
      .mockResolvedValueOnce(stored)

    render(<FileUploadDemo />)
    chooseFile()
    await userEvent.setup().click(screen.getByRole('button', { name: '上传' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('登记响应丢失'))
    expect(screen.getByText('失败')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('button', { name: '重试登记' }))
    await waitFor(() => expect(screen.getByText('登记完成')).toBeInTheDocument())
    expect(mockComplete).toHaveBeenCalledTimes(2) // same grant retried
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('surfaces a direct-upload failure without attempting registration', async () => {
    mockGrant.mockResolvedValue(grant)
    mockPut.mockRejectedValue(new Error('直传失败：网络错误'))

    render(<FileUploadDemo />)
    chooseFile()
    await userEvent.setup().click(screen.getByRole('button', { name: '上传' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('直传失败'))
    expect(mockComplete).not.toHaveBeenCalled()
  })
})

import { act } from 'react'
