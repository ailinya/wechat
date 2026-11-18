/** Collection management API calls (task 3.9). */

import { apiRequest } from './client'
import type {
  AsyncJobAccepted,
  BulkResultOut,
  CollectionResultOut,
  CollectionRunOut,
  CollectionSourceIn,
  CollectionSourceOut,
  CollectionTaskIn,
  CollectionTaskOut,
  PaginatedResponse_CollectionResultOut_,
  PaginatedResponse_CollectionRunOut_,
  PaginatedResponse_CollectionSourceOut_,
  PaginatedResponse_CollectionTaskOut_,
  SourceTestResult,
} from './types'

function pageQuery(page: number, pageSize: number, params: Record<string, string | undefined> = {}) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value)
  return query.toString()
}

export const collectionApi = {
  listSources: (page: number, pageSize: number, keyword?: string) =>
    apiRequest<PaginatedResponse_CollectionSourceOut_>(
      `/collection/sources?${pageQuery(page, pageSize, { keyword })}`,
    ),
  createSource: (payload: CollectionSourceIn) =>
    apiRequest<CollectionSourceOut>('/collection/sources', { method: 'POST', body: payload }),
  testSource: (id: string) =>
    apiRequest<SourceTestResult>(`/collection/sources/${id}/test`, { method: 'POST' }),

  listTasks: (page: number, pageSize: number, status?: string) =>
    apiRequest<PaginatedResponse_CollectionTaskOut_>(
      `/collection/tasks?${pageQuery(page, pageSize, { status })}`,
    ),
  createTask: (payload: CollectionTaskIn) =>
    apiRequest<CollectionTaskOut>('/collection/tasks', { method: 'POST', body: payload }),
  runTask: (id: string) =>
    apiRequest<AsyncJobAccepted>(`/collection/tasks/${id}/run`, { method: 'POST' }),
  pauseTask: (id: string) =>
    apiRequest<CollectionTaskOut>(`/collection/tasks/${id}/pause`, { method: 'POST' }),
  resumeTask: (id: string) =>
    apiRequest<CollectionTaskOut>(`/collection/tasks/${id}/resume`, { method: 'POST' }),

  listRuns: (page: number, pageSize: number, taskId?: string, status?: string) =>
    apiRequest<PaginatedResponse_CollectionRunOut_>(
      `/collection/runs?${pageQuery(page, pageSize, { task_id: taskId, status })}`,
    ),

  listResults: (
    page: number,
    pageSize: number,
    params: { runId?: string; parseStatus?: string; materializeStatus?: string } = {},
  ) =>
    apiRequest<PaginatedResponse_CollectionResultOut_>(
      `/collection/results?${pageQuery(page, pageSize, {
        run_id: params.runId,
        parse_status: params.parseStatus,
        materialize_status: params.materializeStatus,
      })}`,
    ),
  materialize: (id: string) =>
    apiRequest<AsyncJobAccepted>(`/collection/results/${id}/materialize`, { method: 'POST' }),
  bulkMaterialize: (resultIds: string[]) =>
    apiRequest<BulkResultOut>('/collection/results/bulk-materialize', {
      method: 'POST',
      body: { result_ids: resultIds },
    }),
  ignoreResult: (id: string) =>
    apiRequest(`/collection/results/${id}/ignore`, { method: 'POST' }),
  retryParse: (id: string) =>
    apiRequest<AsyncJobAccepted>(`/collection/results/${id}/retry-parse`, { method: 'POST' }),
}

export type { CollectionResultOut, CollectionRunOut, CollectionSourceOut, CollectionTaskOut }
