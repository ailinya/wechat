import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from './client'

afterEach(() => vi.unstubAllGlobals())

describe('旧客户端错误与异步契约兼容', () => {
  it('保留新错误码和字段错误，供旧调用方显示', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'outbox_recovery_blocked', message: '请先核对远端结果', field_errors: [{ field: 'revision_id', message: '版本已变化' }] } }), { status: 409 })))
    await expect(apiRequest('/settings/outbox/example/retry', { method: 'POST' })).rejects.toMatchObject({ status: 409, code: 'outbox_recovery_blocked', message: '请先核对远端结果', fieldErrors: [{ field: 'revision_id', message: '版本已变化' }] })
  })
  it('代理非 JSON 错误与断网均变为可展示的错误', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('<html>upstream unavailable</html>', { status: 502 })).mockRejectedValueOnce(new TypeError('connection reset'))
    vi.stubGlobal('fetch', fetch)
    await expect(apiRequest('/dashboard')).rejects.toMatchObject({ status: 502, code: 'request_failed' })
    await expect(apiRequest('/dashboard')).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })
  it('202 保留作业标识及新增字段，204 不解析正文', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ async_job_id: 'job', resource_id: 'resource', status: 'pending', extra: 'future' }), { status: 202 })).mockResolvedValueOnce(new Response(null, { status: 204 })))
    await expect(apiRequest('/creation-tasks', { method: 'POST', body: {} })).resolves.toMatchObject({ async_job_id: 'job', resource_id: 'resource', status: 'pending' })
    await expect(apiRequest('/resource', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})
