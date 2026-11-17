/** Tests for the job polling hook (task 2.8). */

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { jobsApi } from '../api/jobs'
import { JOB_POLL_INTERVAL_MS, useJobPolling } from './useJobPolling'

vi.mock('../api/jobs', () => ({
  jobsApi: { get: vi.fn(), cancel: vi.fn() },
}))

const mockGet = vi.mocked(jobsApi.get)

const runningJob = {
  id: 'job-1', job_type: 'tests.demo', resource_type: 'tests',
  resource_id: '00000000-0000-0000-0000-000000000001', status: 'running' as const,
  stage: 'fetching', progress: 40, attempts: 1, last_error: null,
  started_at: null, finished_at: null, created_at: '', updated_at: '',
}

const doneJob = { ...runningJob, status: 'succeeded' as const, progress: 100 }

beforeEach(() => {
  vi.useFakeTimers()
  mockGet.mockReset()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('useJobPolling', () => {
  it('stops polling when the job reaches a terminal state', async () => {
    mockGet
      .mockResolvedValueOnce(runningJob)
      .mockResolvedValueOnce(doneJob)

    const { result } = renderHook(() => useJobPolling({ jobId: 'job-1' }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(result.current.job?.status).toBe('running')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS)
    })
    expect(mockGet).toHaveBeenCalledTimes(2)
    expect(result.current.job?.status).toBe('succeeded')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS * 3)
    })
    expect(mockGet).toHaveBeenCalledTimes(2) // no further polls
  })

  it('keeps polling through a transient failure and reports the error', async () => {
    mockGet
      .mockRejectedValueOnce(new Error('网络请求失败，请稍后重试'))
      .mockResolvedValueOnce(doneJob)

    const { result } = renderHook(() => useJobPolling({ jobId: 'job-1' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.error).toContain('网络请求失败')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS)
    })
    expect(mockGet).toHaveBeenCalledTimes(2)
    expect(result.current.job?.status).toBe('succeeded')
    expect(result.current.error).toBeNull()
  })

  it('stops polling entirely on 404', async () => {
    mockGet.mockRejectedValue(Object.assign(new Error('任务不存在'), { status: 404 }))

    const { result } = renderHook(() => useJobPolling({ jobId: 'gone' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(mockGet).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS * 3)
    })
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(result.current.error).toContain('任务不存在')
  })

  it('stops all timers on unmount', async () => {
    mockGet.mockResolvedValue(runningJob)
    const { unmount } = renderHook(() => useJobPolling({ jobId: 'job-1' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS * 5)
    })
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('cancel() fetches and applies the cancelled job', async () => {
    const cancelled = { ...runningJob, status: 'cancelled' as const }
    mockGet.mockResolvedValue(runningJob)
    vi.mocked(jobsApi.cancel).mockResolvedValue(cancelled)

    const { result } = renderHook(() => useJobPolling({ jobId: 'job-1' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    await act(async () => {
      await result.current.cancel()
    })
    expect(result.current.job?.status).toBe('cancelled')
  })

  it('renders nothing without a job id', () => {
    const { result } = renderHook(() => useJobPolling({ jobId: null }))
    expect(result.current.job).toBeNull()
    expect(mockGet).not.toHaveBeenCalled()
  })
})
