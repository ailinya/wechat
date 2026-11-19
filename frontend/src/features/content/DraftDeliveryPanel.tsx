import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../app/AuthContext'
import { accountsApi, draftsApi, draftLabels, wechatErrorMessage, type Account, type DraftDelivery, type DraftAttempt } from '../../shared/api/wechat'
import type { Page } from '../../shared/api/articles'

export function DraftDeliveryPanel({ articleId, revisionId, articleStatus, dirty = false, onPublished }: { articleId: string; revisionId: string; articleStatus: string; dirty?: boolean; onPublished?: () => void }) {
  const { hasPermission } = useAuth()
  const read = hasPermission('publish:read'), confirm = hasPermission('publish:confirm'), accountRead = hasPermission('account:read')
  const [accounts, setAccounts] = useState<Account[]>([])
  const [deliveries, setDeliveries] = useState<Page<DraftDelivery> | null>(null)
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState('')
  const [attempts, setAttempts] = useState<DraftAttempt[]>([])
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [outcome, setOutcome] = useState<'query' | 'not_synced'>('query')
  const selected = deliveries?.items.find(row => row.id === selectedId)
  const active = deliveries?.items.some(row => ['pending', 'preparing', 'syncing'].includes(row.status))
  useEffect(() => {
    if (!read) return
    let live = true
    void draftsApi.list(articleId, page).then(value => {
      if (!live) return
      setDeliveries(value)
      if (value.items.some(row => row.status === 'manual_published' && row.article_revision_id === revisionId)) onPublished?.()
    }).catch(cause => { if (live) setError(cause.message) })
    return () => { live = false }
  }, [read, articleId, page, refresh, revisionId, onPublished])
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setRefresh(value => value + 1), 3000)
    return () => window.clearInterval(timer)
  }, [active])
  useEffect(() => {
    if (!read || !accountRead) return
    let live = true
    void accountsApi.list().then(value => { if (live) setAccounts(value.items) }).catch(cause => { if (live) setError(cause.message) })
    return () => { live = false }
  }, [read, accountRead, refresh])
  useEffect(() => {
    if (!read || !selectedId) return
    let live = true
    void draftsApi.attempts(selectedId).then(value => { if (live) setAttempts(value) }).catch(cause => { if (live) setError(cause.message) })
    return () => { live = false }
  }, [read, selectedId, refresh])
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await work(); setRefresh(value => value + 1) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }
  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    void act(async () => {
      const value = await draftsApi.create({ article_revision_id: revisionId, account_id: String(data.get('account')), confirm_sync: true, note: String(data.get('note') || '') }, crypto.randomUUID())
      setPage(1); setSelectedId(value.id); setMessage('同步已受理，完成后请到微信后台手动发布。')
    })
  }
  if (!read) return null
  const current = selected?.article_revision_id === revisionId
  return <section className="publish-panel" aria-label="微信草稿箱"><h2>同步到微信草稿箱</h2><p>审核通过 → 同步微信草稿 → 在公众号后台手动发布。同步成功后，文章仍保持审核通过。</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    <a href="https://mp.weixin.qq.com/" target="_blank" rel="noopener noreferrer">打开微信公众平台</a> <button onClick={() => setRefresh(value => value + 1)}>刷新草稿状态</button>
    {confirm && articleStatus === 'approved' && <form className="collection-form" onSubmit={create}><fieldset disabled={busy || dirty}><legend>确认同步当前已审核版本</legend>
      <label>草稿目标公众号<select name="account" required defaultValue=""><option value="">请选择账号</option>{accounts.map(item => <option key={item.id} value={item.id} disabled={item.status !== 'active' || !item.capabilities.drafts?.available}>{item.name}{item.status !== 'active' || !item.capabilities.drafts?.available ? '（草稿能力不可用）' : ''}</option>)}</select></label>
      <p>草稿读取检测通过不代表写入一定可用；微信拒绝时会显示具体原因。</p><label>同步备注<textarea name="note" maxLength={2000} /></label>
      <label><input type="checkbox" required />我已核对当前审核版本和目标公众号，确认同步草稿</label><button>确认同步到微信草稿箱</button>
    </fieldset></form>}
    {dirty && <p>请先保存修改并重新审核，再同步新版本。</p>}
    {!deliveries ? <p role="status">正在加载草稿交付…</p> : deliveries.items.length === 0 ? <p>暂无草稿交付记录</p> : <ul>{deliveries.items.map(row => <li key={row.id}><button onClick={() => { setSelectedId(row.id); setAttempts([]); setOutcome('query') }}>{draftLabels[row.status]} · {accounts.find(item => item.id === row.account_id)?.name || row.account_id}</button>{row.article_revision_id !== revisionId && '（非当前版本）'}</li>)}</ul>}
    <button disabled={page <= 1} onClick={() => { setSelectedId(''); setPage(value => value - 1) }}>上一页草稿</button><button disabled={!deliveries || page * 20 >= deliveries.total} onClick={() => { setSelectedId(''); setPage(value => value + 1) }}>下一页草稿</button>
    {selected && <section aria-label="草稿交付详情"><h3>{draftLabels[selected.status]}</h3><p>绑定审核版本：{selected.article_revision_id}{!current && '（非当前版本，须重新审核并同步新版）'}</p><p>确认人：{selected.confirmed_by} · {new Date(selected.confirmed_at).toLocaleString()}</p>{selected.remote_media_id && <p>微信草稿 media_id：{selected.remote_media_id}</p>}{selected.error_code && <p role="alert">{wechatErrorMessage(selected.error_code)}</p>}
      {confirm && ['pending', 'preparing'].includes(selected.status) && <button disabled={busy} onClick={() => void act(async () => { await draftsApi.action(selected.id, 'cancel', crypto.randomUUID()); setMessage('草稿交付已取消。') })}>取消草稿同步</button>}
      {confirm && selected.status === 'failed' && <button disabled={busy || dirty || !current} onClick={() => void act(async () => { await draftsApi.action(selected.id, 'retry', crypto.randomUUID()); setMessage('已受理重试，保留之前的尝试记录。') })}>重试草稿同步</button>}
      {confirm && selected.status === 'unknown' && <form className="collection-form" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void act(async () => { const value = await draftsApi.reconcile(selected.id, { outcome, note: String(data.get('evidence') || '') }); setMessage(`核对完成：${draftLabels[value.status]}`) }) }}><label>草稿核对方式<select value={outcome} onChange={event => setOutcome(event.target.value as typeof outcome)}><option value="query">查询微信草稿匹配结果</option><option value="not_synced">已在微信后台确认未同步</option></select></label><label>后台核对依据<textarea name="evidence" required={outcome === 'not_synced'} maxLength={2000} /></label><button disabled={busy}>核对草稿结果</button></form>}
      {confirm && selected.status === 'awaiting_manual_publish' && current && <form className="collection-form" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void act(async () => { await draftsApi.manualPublished(selected.id, { content_matches_revision: true, article_url: String(data.get('url')), note: String(data.get('manualNote')) }); setMessage('已保存人工发布登记。'); onPublished?.() }) }}><fieldset disabled={busy || dirty}><legend>完成微信后台发布后，人工登记</legend><label>微信文章链接<input name="url" type="url" required placeholder="https://mp.weixin.qq.com/s/…" /></label><label>人工发布说明<textarea name="manualNote" required maxLength={2000} /></label><label><input type="checkbox" required />我已在微信后台发布，确认内容与本审核版本一致</label><p>此记录来源为人工登记。</p><button>登记已手动发布</button></fieldset></form>}
      {selected.status === 'manual_published' && <p>来源：人工登记 · {selected.manual_published_by} · {selected.manual_published_at && new Date(selected.manual_published_at).toLocaleString()} · {selected.manual_note} {selected.manual_article_url && <a href={selected.manual_article_url} target="_blank" rel="noopener noreferrer">查看登记的微信文章</a>}</p>}
      <h3>草稿同步尝试历史</h3>{!attempts.length && <p>尚无执行尝试</p>}{attempts.map(item => <article key={item.id}><p>第 {item.attempt_no} 次 · {draftLabels[item.status] || item.status} · {new Date(item.started_at).toLocaleString()}</p>{item.error_code && <p>{wechatErrorMessage(item.error_code)}</p>}{item.reconciliation_note && <p>核对依据：{item.reconciliation_note}</p>}</article>)}
    </section>}
  </section>
}
