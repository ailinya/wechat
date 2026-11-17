/** Async job query and cancellation API calls (task 2.8). */

import { apiRequest } from './client'
import type { AsyncJobOut } from './types'

export interface JobListParams {
  page?: number
  pageSize?: number
  jobType?: string
  status?: string
}

export const jobsApi = {
  get: (jobId: string) => apiRequest<AsyncJobOut>(`/async-jobs/${jobId}`),

  cancel: (jobId: string) =>
    apiRequest<AsyncJobOut>(`/async-jobs/${jobId}/cancel`, { method: 'POST' }),

  list: ({ page = 1, pageSize = 20, jobType, status }: JobListParams = {}) => {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (jobType) query.set('job_type', jobType)
    if (status) query.set('status', status)
    return apiRequest<import('./types').PaginatedResponse_AsyncJobOut_>(`/async-jobs?${query}`)
  },
}
