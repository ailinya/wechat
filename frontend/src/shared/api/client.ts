/** Typed fetch client for the /api/v1 contract. */

import type { ErrorEnvelope } from './types'

const API_BASE = '/api/v1'
const CSRF_COOKIE = 'wetchat_csrf'
const CSRF_HEADER = 'X-CSRF-Token'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fieldErrors: { field: string; message: string }[]

  constructor(
    status: number,
    code: string,
    message: string,
    fieldErrors: { field: string; message: string }[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fieldErrors = fieldErrors
  }
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  for (const part of document.cookie.split('; ')) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length))
  }
  return null
}

export function getCsrfToken(): string | null {
  return readCookie(CSRF_COOKIE)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  /** Extra request headers (e.g. Idempotency-Key). */
  headers?: Record<string, string>
}

/** Perform an authenticated API request. Cookies are always included. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  const isWrite = method !== 'GET'

  if (isWrite) {
    headers[CSRF_HEADER] = getCsrfToken() ?? ''
    if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  }
  Object.assign(headers, options.headers)

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (cause) {
    throw new ApiError(0, 'network_error', '网络请求失败，请稍后重试')
  }

  if (response.status === 204) return undefined as T

  let payload: unknown = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      if (response.ok) throw new ApiError(response.status, 'invalid_response', '响应格式错误')
    }
  }

  if (!response.ok) {
    const envelope = payload as ErrorEnvelope | null
    const detail = envelope?.error
    throw new ApiError(
      response.status,
      detail?.code ?? 'request_failed',
      detail?.message ?? `请求失败（${response.status}）`,
      detail?.field_errors ?? [],
    )
  }

  return payload as T
}
