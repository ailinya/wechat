/** Authentication API calls. */

import { apiRequest } from './client'
import type { CurrentUser, LoginRequest, LoginResponse, OkResponse } from './types'

export const authApi = {
  login: (account: string, password: string) =>
    apiRequest<LoginResponse>('/auth/login', {
      method: 'POST',
      body: { account, password } satisfies LoginRequest,
    }),

  logout: () => apiRequest<OkResponse>('/auth/logout', { method: 'POST' }),

  me: () => apiRequest<CurrentUser>('/auth/me'),
}
