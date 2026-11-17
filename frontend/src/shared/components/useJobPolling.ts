/** Poll an async job until it reaches a terminal state (task 2.8).
 *
 * - Stops automatically on succeeded/failed/cancelled.
 * - Network failures keep polling (transient) but surface the last error.
 * - Timers are cleared when the job id changes or the component unmounts.
 * - Pass a job id from the URL to restore state after a refresh.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { jobsApi } from '../api/jobs'
import type { AsyncJobOut } from '../api/types'

export type JobStatus = AsyncJobOut['status']
export const JOB_TERMINAL_STATUSES: JobStatus[] = ['succeeded', 'failed', 'cancelled']

export const JOB_POLL_INTERVAL_MS = 2000

interface Options {
  /** null = not polling */
  jobId: string | null
  intervalMs?: number
}

export interface JobPollingResult {
  job: AsyncJobOut | null
  error: string | null
  /** true between a started fetch and its settle; distinct from "no job yet" */
  refreshing: boolean
  cancel: () => Promise<void>
  refresh: () => void
}

export function useJobPolling({ jobId, intervalMs = JOB_POLL_INTERVAL_MS }: Options): JobPollingResult {
  const [job, setJob] = useState<AsyncJobOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const mounted = useRef(true)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (timer.current !== null) window.clearTimeout(timer.current)
    }
  }, [])

  const schedule = useCallback(
    (delay: number) => {
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => {
        if (mounted.current) setAttempt((value) => value + 1)
      }, delay)
    },
    [],
  )

  useEffect(() => {
    if (!jobId) {
      setJob(null)
      setError(null)
      return
    }

    let cancelled = false
    setRefreshing(true)

    jobsApi
      .get(jobId)
      .then((next) => {
        if (cancelled || !mounted.current) return
        setJob(next)
        setError(null)
        if (!JOB_TERMINAL_STATUSES.includes(next.status)) schedule(intervalMs)
      })
      .catch((cause: unknown) => {
        if (cancelled || !mounted.current) return
        // Keep polling through transient failures (e.g. network blips); a
        // 404 surfaces as an error and stops the loop via terminal check.
        setError(cause instanceof Error ? cause.message : '任务查询失败')
        const status = (cause as { status?: number })?.status
        if (status !== 404) schedule(intervalMs)
      })
      .finally(() => {
        if (!cancelled && mounted.current) setRefreshing(false)
      })

    return () => {
      cancelled = true
    }
  }, [jobId, attempt, intervalMs, schedule])

  const cancel = useCallback(async () => {
    if (!jobId) return
    const next = await jobsApi.cancel(jobId)
    setJob(next)
  }, [jobId])

  const refresh = useCallback(() => setAttempt((value) => value + 1), [])

  return { job, error, refreshing, cancel, refresh }
}
