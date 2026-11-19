import { useEffect, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { operationsApi } from '../../shared/api/operations'
import type { RuntimeOut, OutboxOut } from '../../shared/api/types'

export function RuntimePanel() {
  const { hasPermission } = useAuth()
  const [runtime, setRuntime] = useState<RuntimeOut | null>(null)
  const [events, setEvents] = useState<OutboxOut[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => {
    let live = true
    void Promise.all([operationsApi.runtime(), operationsApi.outbox(page)])
      .then(([state, outbox]) => { if (live) { setRuntime(state); setEvents(outbox.items); setTotal(outbox.total); setError('') } })
      .catch(cause => { if (live) setError(cause.message) })
    return () => { live = false }
  }, [page, refresh])
  async function act(work: () => Promise<unknown>, success: string) {
    setBusy(true); setError(''); setMessage('')
    try { await work(); setMessage(success); setRefresh(value => value + 1) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '恢复操作失败') }
    finally { setBusy(false) }
  }
  return <section className="ops-card"><h2>运行恢复</h2>
    <p>超时任务回收后保留执行历史。微信结果未知时，请到对应发布记录核对远端结果。</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {runtime ? <p>卡住任务 {runtime.stale_running_jobs} · 超时待执行 {runtime.stale_pending_jobs} · 待投递 {runtime.pending_outbox} · 投递失败 {runtime.failed_outbox} · 发布结果未知 {runtime.unknown_publications} · 草稿结果未知 {runtime.unknown_drafts}</p> : <p role="status">正在检查运行状态…</p>}
    <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>刷新运行状态</button>
    {hasPermission('settings:write') && <button disabled={busy || !runtime} onClick={() => void act(operationsApi.recoverStale, '已检查并回收超时任务，请到业务页面确认后续处理。')}>回收超时任务</button>}
    <h3>消息投递记录</h3><div className="ops-scroll"><table><thead><tr><th>事件</th><th>状态</th><th>尝试次数</th><th>操作</th></tr></thead><tbody>
      {events.map(event => <tr key={event.id}><td>{event.event_type}<p>{event.id}</p></td><td>{event.status}</td><td>{event.attempts}</td><td>{event.status === 'failed' && hasPermission('settings:write') && <button disabled={busy} onClick={() => void act(() => operationsApi.retryOutbox(event.id), '已恢复投递；后台仅接受原任务尚未执行的事件。')}>恢复未执行任务的投递</button>}</td></tr>)}
    </tbody></table>{!events.length && runtime && <p>暂无投递记录</p>}</div>
    <div className="ops-pagination"><button disabled={page <= 1 || busy} onClick={() => setPage(value => value - 1)}>上一页投递</button><span>第{page}页，共{total}条</span><button disabled={page * 20 >= total || busy} onClick={() => setPage(value => value + 1)}>下一页投递</button></div>
  </section>
}
