import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../app/AuthContext'
import { navigate, useHashRoute } from '../../app/router'
import { accountsApi, wechatErrorMessage, type Account, type SyncRun } from '../../shared/api/wechat'
import type { Page } from '../../shared/api/articles'

const statusLabels: Record<string, string> = { active: '连接正常', invalid: '连接异常', unbound: '已解绑', pending: '等待执行', running: '执行中', succeeded: '已完成', failed: '失败' }

export function AccountsPage() {
  const { hasPermission } = useAuth()
  const writable = hasPermission('account:write')
  const { query } = useHashRoute()
  const page = Math.max(1, Number(query.get('page')) || 1)
  const selectedId = query.get('account_id') || ''
  const [accounts, setAccounts] = useState<Page<Account> | null>(null)
  const [selected, setSelected] = useState<Account | null>(null)
  const [runs, setRuns] = useState<Page<SyncRun> | null>(null)
  const [runPage, setRunPage] = useState(1)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [secret, setSecret] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setSelected(null); setSecret('')
    void Promise.all([accountsApi.list(page), selectedId ? accountsApi.detail(selectedId) : Promise.resolve(null)]).then(([list, detail]) => { if (active) { setAccounts(list); setSelected(detail) } }).catch(cause => { if (active) setError(cause.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [page, selectedId, reload])
  useEffect(() => {
    if (!selectedId) return
    let active = true
    let timer: number | undefined
    async function poll() {
      try { const value = await accountsApi.runs(selectedId, runPage); if (!active) return; setRuns(value); if (value.items.some(item => ['pending', 'running'].includes(item.status))) timer = window.setTimeout(() => void poll(), 3000) }
      catch (cause) { if (active) setError(cause instanceof Error ? cause.message : '同步历史加载失败') }
    }
    setRuns(null); void poll()
    return () => { active = false; window.clearTimeout(timer) }
  }, [selectedId, runPage, reload])
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await work(); setReload(value => value + 1) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }
  function choose(id: string) { setRunPage(1); navigate('/accounts', new URLSearchParams({ page: String(page), account_id: id })) }
  async function bind(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget, data = new FormData(form)
    await act(async () => {
      const value = await accountsApi.bind({ name: String(data.get('name')), app_id: String(data.get('appid')), app_secret: String(data.get('secret')), account_type: String(data.get('type')), publish_permission_confirmed: data.has('confirmed') })
      form.reset(); choose(value.id); setMessage('公众号直连接入成功，能力以检测结果为准。')
    })
  }
  return <section className="list-page"><h1>公众号账号管理</h1><p>自有公众号直连。使用账号自己的 AppID/AppSecret；请将服务器出口 IP 加入微信 API 白名单。</p>
    {error && <p role="alert">{error}<button onClick={() => setReload(value => value + 1)}>刷新重试</button></p>}{message && <p role="status">{message}</p>}
    {writable && <details><summary>接入公众号</summary><form className="collection-form" onSubmit={event => void bind(event)}>
      <label>公众号名称<input name="name" required maxLength={128} /></label><label>账号类型<select name="type"><option value="subscription">公众号（订阅号）</option><option value="service">服务号</option></select></label>
      <label>AppID<input name="appid" required pattern="wx[0-9a-fA-F]{16}" autoComplete="off" /></label><label>AppSecret<input name="secret" type="password" required minLength={16} maxLength={256} autoComplete="new-password" /></label>
      <label><input name="confirmed" type="checkbox" />我已在微信后台核实该账号具有发布接口权限</label><p>名称与类型由人工填写。连接检测只读接口，不会发布文章；只读成功不能单独证明发布权限。</p><button disabled={busy}>校验凭据并接入</button>
    </form></details>}
    {loading ? <p role="status">正在加载账号…</p> : accounts && <><p>共 {accounts.total} 个账号</p>{accounts.items.length === 0 && <p>暂无已接入公众号</p>}<div className="table-scroll"><table><thead><tr><th>公众号</th><th>连接</th><th>默认账号</th><th>最近检测</th><th>操作</th></tr></thead><tbody>{accounts.items.map(item => <tr key={item.id}><td>{item.name}<br /><small>{item.app_id}</small></td><td>{statusLabels[item.status]}</td><td>{item.is_default ? '是' : '否'}</td><td>{item.checked_at ? new Date(item.checked_at).toLocaleString() : '未检测'}</td><td><button onClick={() => choose(item.id)}>查看账号</button></td></tr>)}</tbody></table></div><button disabled={page <= 1} onClick={() => navigate('/accounts', new URLSearchParams({ page: String(page-1) }))}>上一页账号</button><button disabled={page*100 >= accounts.total} onClick={() => navigate('/accounts', new URLSearchParams({ page: String(page+1) }))}>下一页账号</button></>}
    {selected && <section aria-label="公众号详情"><h2>{selected.name}</h2><p>{statusLabels[selected.status]} · AppID：{selected.app_id} · {selected.account_type === 'service' ? '服务号' : '订阅号'}（名称与类型为人工资料）</p><p>密钥：{selected.credential_configured ? '已配置，不回显' : '未配置'} · 接入时间：{new Date(selected.authorized_at).toLocaleString()}</p>{selected.error_code && <p role="alert">连接错误：{wechatErrorMessage(selected.error_code)}</p>}
      <h3>接口能力</h3>{Object.entries(selected.capabilities).map(([key, value]) => <p key={key}>{({ materials: '永久图文读取', drafts: '草稿读取', draft_write: '草稿写入', published_read: '发布记录读取', publish: '发布' } as Record<string, string>)[key] || key}：{value.available ? '可用' : '不可用'} · {value.reason}</p>)}
      {writable && <><div className="form-actions"><button disabled={busy || selected.status === 'unbound'} onClick={() => void act(async () => { await accountsApi.check(selected.id); setMessage('已完成连接检测，请查看各项能力。') })}>重新检测</button><button disabled={busy || selected.status !== 'active'} onClick={() => void act(async () => { await accountsApi.setDefault(selected.id); setMessage('已设置默认账号；发布单仍须逐次确认。') })}>设为默认账号</button><button disabled={busy || selected.status === 'unbound'} onClick={() => void act(async () => { await accountsApi.unbind(selected.id); setMessage('已解除绑定，历史记录保留。') })}>解除绑定</button><button disabled={busy || !selected.capabilities.materials?.available || selected.status !== 'active'} onClick={() => void act(async () => { await accountsApi.sync(selected.id, crypto.randomUUID()); setMessage('素材同步已受理，尚未完成。') })}>同步永久图文</button></div>
      <label>重新接入 AppSecret<input type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="new-password" /></label><button disabled={busy || secret.length < 16} onClick={() => void act(async () => { await accountsApi.reconnect(selected.id, secret); setSecret(''); setMessage('新凭据校验成功。') })}>校验并重新接入</button>
      {selected.status === 'active' && <form className="collection-form" key={selected.credential_version} onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void act(async () => { await accountsApi.update(selected.id, { name: data.get('name'), publish_permission_confirmed: data.has('confirmed'), publish_defaults: { need_open_comment: data.has('comments'), only_fans_can_comment: data.has('fans') } }); setMessage('账号配置已保存，既有发布单参数保持原快照。') }) }}><label>显示名称<input name="name" required defaultValue={selected.name} /></label><label><input name="confirmed" type="checkbox" defaultChecked={selected.publish_permission_confirmed} />已核实微信后台发布接口权限</label><label><input name="comments" type="checkbox" defaultChecked={selected.publish_defaults.need_open_comment} />默认开启评论</label><label><input name="fans" type="checkbox" defaultChecked={selected.publish_defaults.only_fans_can_comment} />默认仅粉丝评论</label><button disabled={busy}>保存账号配置</button></form>}
      </>}
      <h3>素材同步历史</h3><p>当前同步范围为永久图文，最多400组/次；不自动同步二进制素材，不覆盖已入库人工内容。</p>{runs?.items.length === 0 && <p>暂无同步记录</p>}{runs?.items.map(item => <article key={item.id}><p>{statusLabels[item.status] || item.status} · 新增 {item.imported_count} · 已有关联 {item.reused_count} · {new Date(item.created_at).toLocaleString()}</p>{item.error_code && <p role="alert">{wechatErrorMessage(item.error_code)}</p>}</article>)}<button disabled={runPage <= 1} onClick={() => setRunPage(value => value-1)}>上一页同步</button><button disabled={!runs || runPage*20 >= runs.total} onClick={() => setRunPage(value => value+1)}>下一页同步</button>
      {hasPermission('publish:read') && <a href={`#/content/publishing?account_id=${selected.id}`}>查看该账号发布记录</a>}
    </section>}
  </section>
}
