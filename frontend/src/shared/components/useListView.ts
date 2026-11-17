/** Fetch hook for paginated list pages: four states, abort, retry. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, apiRequest } from '../api/client'
import { ListStates, type ListStatus } from './states'

interface ListViewOptions {
  page: number
  pageSize: number
  params?: Record<string, string | undefined>
}

export interface ListViewResult<T> {
  status: ListStatus
  error: string | null
  data: { items: T[]; total: number; page: number; page_size: number } | null
  retry: () => void
}

/** Run a GET against a PaginatedResponse endpoint and map failures onto the
 * shared states: 403 -> forbidden, other errors -> error, empty page -> empty. */
export function useListView<T>(path: string, options: ListViewOptions): ListViewResult<T> {
  const [status, setStatus] = useState<ListStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<ListViewResult<T>['data']>(null)
  const [attempt, setAttempt] = useState(0)
  const controllerRef = useRef<AbortController | null>(null)

  const query = new URLSearchParams({ page: String(options.page), page_size: String(options.pageSize) })
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value) query.set(key, value)
  }
  const queryString = query.toString()

  useEffect(() => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setStatus('loading')
    setError(null)

    apiRequest<{ items: T[]; total: number; page: number; page_size: number }>(
      `${path}?${queryString}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (controller.signal.aborted) return
        setData(result)
        setStatus(result.items.length === 0 ? 'empty' : 'ready')
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        if (cause instanceof ApiError) {
          if (cause.status === 403) {
            setError(null)
            setStatus('forbidden')
            return
          }
          setError(cause.message)
        } else {
          setError('请求失败，请稍后重试')
        }
        setStatus('error')
      })

    return () => controller.abort()
  }, [path, queryString, attempt])

  const retry = useCallback(() => setAttempt((value) => value + 1), [])

  return { status, error, data, retry }
}

export { ListStates }
