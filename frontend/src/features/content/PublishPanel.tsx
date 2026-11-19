import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../app/AuthContext'
import { accountsApi, publishingApi, publishLabels, wechatErrorMessage, type Account, type PublishOrder, type PublishAttempt } from '../../shared/api/wechat'
import type { Page } from '../../shared/api/articles'

export function PublishPanel({ articleId, revisionId, articleStatus, dirty = false, onPublished }: { articleId: string; revisionId: string; articleStatus: string; dirty?: boolean; onPublished?: () => void }) {
  const { hasPermission } = useAuth()
  const readable = hasPermission('publish:read')
  const confirm = hasPermission('publish:confirm')
  const execute = hasPermission('publish:execute')
  const accountRead = hasPermission('account:read')
  const [accounts, setAccounts] = useState<Account[]>([])
  const [orders, setOrders] = useState<Page<PublishOrder> | null>(null)
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('order_id') || '')
  const [attempts, setAttempts] = useState<PublishAttempt[]>([])
  const [selectedDetail, setSelectedDetail] = useState<PublishOrder | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [mode, setMode] = useState('immediate')
  const [outcome, setOutcome] = useState('query')
  const selected = selectedDetail?.id === selectedId ? selectedDetail : orders?.items.find(row => row.id === selectedId)
  const active = orders?.items.some(row => ['confirmed', 'preparing', 'submitting', 'publishing'].includes(row.status))
  useEffect(() => {
    if (!readable) return
    let live = true
    void publishingApi.list(articleId, page).then(value => { if (live) { setOrders(value); if (value.items.some(row => row.status === 'succeeded' && row.article_revision_id === revisionId)) onPublished?.() } }).catch(cause => { if (live) setError(cause.message) })
    return () => { live = false }
  }, [readable, articleId, page, refresh, revisionId, onPublished])
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setRefresh(value => value + 1), 3000)
    return () => window.clearInterval(timer)
  }, [active])
  useEffect(() => {
    if (!readable || !accountRead) return
    let live = true
    void accountsApi.list().then(value => { if (live) setAccounts(value.items) }).catch(cause => { if (live) setError(cause.message) })
    return () => { live = false }
  }, [readable, accountRead, refresh])
  useEffect(() => {
    if (!readable || !selectedId) return
    let live = true
    void Promise.all([publishingApi.attempts(selectedId), publishingApi.detail(selectedId)]).then(([value, detail]) => { if (live) { if (detail.article_id !== articleId) { setError('发布单不属于当前文章'); return } setAttempts(value); setSelectedDetail(detail) } }).catch(cause => { if (live) setError(cause.message) })
    return () => { live = false }
  }, [readable, selectedId, refresh, articleId])
  function choose(id: string) {
    setSelectedId(id); setOutcome('query'); setAttempts([])
    const [path, search = ''] = window.location.hash.split('?')
    const query = new URLSearchParams(search); query.set('order_id', id)
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${path}?${query}`)
  }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await work(); setRefresh(value => value + 1) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await act(async () => {
      const value = await publishingApi.create({ article_revision_id: revisionId, account_id: form.get('account'), mode, scheduled_at: mode === 'scheduled' ? new Date(String(form.get('time'))).toISOString() : null, publish_note: form.get('note') || '' }, crypto.randomUUID())
      setPage(1); choose(value.id); setMessage('发布单已保存，尚未确认执行。请核对版本、账号和时间。')
    })
  }
  if (!readable) return null
  return <section className="publish-panel" aria-label="发布管理"><h2>运营确认与发布</h2><p>创建发布单后，仍需明确确认。微信提交受理后还须查询结果；未知结果须先核对。</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}<button onClick={() => setRefresh(value => value + 1)}>刷新发布状态</button>
    {confirm && ['approved', 'published'].includes(articleStatus) && <form className="collection-form" onSubmit={event => void create(event)}><fieldset disabled={busy || dirty}><legend>为当前已审核版本创建发布单</legend>
      <label>目标公众号<select name="account" required defaultValue={accounts.find(item => item.is_default && item.status === 'active' && item.capabilities.publish?.available)?.id || ''}><option value="">请选择账号</option>{accounts.map(item => <option key={item.id} value={item.id} disabled={item.status !== 'active' || !item.capabilities.publish?.available}>{item.name}{item.status !== 'active' || !item.capabilities.publish?.available ? '（当前不可发布）' : ''}</option>)}</select></label>
      <label>发布方式<select value={mode} onChange={e => setMode(e.target.value)}><option value="immediate">确认后立即执行</option><option value="scheduled">定时发布</option></select></label>
      {mode === 'scheduled' && <label>发布时间（本地时间）<input name="time" type="datetime-local" required /></label>}
      <label>发布备注<textarea name="note" maxLength={2000} /></label><button>创建待确认发布单</button>
    </fieldset></form>}
    {dirty && <p>请先保存并重新审核当前修改，再配置发布。</p>}
    {!orders ? <p role="status">正在加载发布单…</p> : orders.items.length === 0 ? <p>暂无发布单</p> : <ul>{orders.items.map(row => <li key={row.id}><button onClick={() => choose(row.id)}>{publishLabels[row.status] || row.status} · {accounts.find(item => item.id === row.account_id)?.name || row.account_id}</button> · 版本 {row.article_revision_id} · {row.scheduled_at ? new Date(row.scheduled_at).toLocaleString() : '立即'}</li>)}</ul>}
    <button disabled={page <= 1} onClick={() => setPage(value => value-1)}>上一页订单</button><button disabled={!orders || page*20 >= orders.total} onClick={() => setPage(value => value+1)}>下一页订单</button>
    {selected && <section aria-label="发布单详情"><h3>{publishLabels[selected.status]}</h3><p>公众号：{accounts.find(item => item.id === selected.account_id)?.name || selected.account_id}</p><p>绑定版本：{selected.article_revision_id}{selected.article_revision_id !== revisionId && '（非当前版本）'}</p><p>执行时间：{selected.mode === 'scheduled' ? new Date(selected.scheduled_at || '').toLocaleString() : '确认后立即执行'}</p><p>评论：{selected.publish_defaults.need_open_comment ? '开启' : '关闭'}；仅粉丝：{selected.publish_defaults.only_fans_can_comment ? '是' : '否'}</p><p>备注：{selected.publish_note || '无'}</p><p>运营确认：{selected.confirmed_at ? `${new Date(selected.confirmed_at).toLocaleString()} · ${selected.confirmed_by}` : '尚未确认'}</p>{selected.error_code && <p role="alert">{wechatErrorMessage(selected.error_code)}</p>}
      {confirm && selected.status === 'awaiting_confirmation' && <button disabled={busy || dirty || selected.article_revision_id !== revisionId} onClick={() => void act(async () => { const value = await publishingApi.action(selected.id, 'confirm', crypto.randomUUID()); setMessage(`已收到确认，当前状态：${publishLabels[value.status]}。`) })}>确认按上述账号、版本和时间发布</button>}
      {confirm && ['awaiting_confirmation', 'confirmed'].includes(selected.status) && <button disabled={busy} onClick={() => void act(async () => { await publishingApi.action(selected.id, 'cancel', crypto.randomUUID()); setMessage('发布单已取消。') })}>取消未执行发布单</button>}
      {execute && selected.status === 'failed' && <button disabled={busy || dirty || selected.article_revision_id !== revisionId} onClick={() => void act(async () => { await publishingApi.action(selected.id, 'retry', crypto.randomUUID()); setMessage('重试已受理，将保留原尝试历史。') })}>重试已确认失败的发布单</button>}
      {execute && ['unknown', 'publishing'].includes(selected.status) && <form className="collection-form" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void act(async () => { const value = await publishingApi.reconcile(selected.id, { outcome, note: data.get('evidence') || '', external_article_id: data.get('external') || null }); setMessage(`核对完成：${publishLabels[value.status]}。`) }) }}><p>有微信任务 ID 时以微信查询结果为准。提交响应丢失时，请在公众号后台核对后记录依据。</p><label>核对方式<select value={outcome} onChange={e => setOutcome(e.target.value)}><option value="query">查询微信发布结果</option><option value="not_published">人工确认未发布</option><option value="published">人工确认已发布</option></select></label><label>核对依据<textarea name="evidence" required={outcome !== 'query'} /></label>{outcome === 'published' && <label>微信文章 ID<input name="external" required /></label>}<button disabled={busy}>提交结果核对</button></form>}
      <h3>发布尝试历史</h3>{!attempts.length && <p>尚无执行尝试</p>}{attempts.map(item => <article key={item.id}><p>第 {item.attempt_no} 次 · {publishLabels[item.status] || item.status} · {new Date(item.started_at).toLocaleString()}</p>{item.publish_id && <p>微信任务：{item.publish_id}</p>}{item.error_code && <p>{wechatErrorMessage(item.error_code)}</p>}{item.reconciliation_note && <p>核对依据：{item.reconciliation_note}</p>}{item.article_url && /^https:\/\/(mp\.weixin\.qq\.com|weixin\.qq\.com)\//.test(item.article_url) && <a href={item.article_url} target="_blank" rel="noopener noreferrer">查看已发布文章</a>}</article>)}
    </section>}
  </section>
}
