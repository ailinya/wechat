/** User management API calls. */

import { apiRequest } from './client'
import type { PaginatedResponse_UserOut_ } from './types'

export interface UserListParams {
  page: number
  pageSize: number
  keyword?: string
  status?: string
}

export const usersApi = {
  list: ({ page, pageSize, keyword, status }: UserListParams) => {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (keyword) query.set('keyword', keyword)
    if (status) query.set('status', status)
    return apiRequest<PaginatedResponse_UserOut_>(`/users?${query.toString()}`)
  },
}
