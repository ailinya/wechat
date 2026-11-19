import { useEffect, useState } from 'react'
import { operationsApi, operationStatus } from '../../shared/api/operations'
import type { NotificationOut, PreferenceOut } from '../../shared/api/types'
import type { Page } from '../../shared/api/articles'

const categories: Record<string,string> = { collection:'采集任务', creation:'创作结果', review:'人工审核', publishing:'发布与草稿', exception:'异常任务' }
export function NotificationsPanel({ preferences = false }: { preferences?: boolean }) {
  const [data,setData] = useState<Page<NotificationOut>|null>(null)
  const [prefs,setPrefs] = useState<PreferenceOut[]>([])
  const [page,setPage] = useState(1),[unread,setUnread] = useState(false),[refresh,setRefresh] = useState(0)
  const [error,setError] = useState(''),[busy,setBusy] = useState(false)
  useEffect(()=>{let live=true;const q=new URLSearchParams({page:String(page),page_size:'10',unread_only:String(unread)});void Promise.all([operationsApi.notifications(q),preferences?operationsApi.preferences():Promise.resolve([])]).then(([value,p])=>{if(live){setData(value);setPrefs(p);setError('')}}).catch(cause=>{if(live)setError(cause.message)});return()=>{live=false}},[page,unread,refresh,preferences])
  async function act(work:()=>Promise<unknown>){setBusy(true);setError('');try{await work();setRefresh(v=>v+1)}catch(cause){setError(cause instanceof Error?cause.message:'操作失败')}finally{setBusy(false)}}
  return <div>{error && <p role="alert">{error}</p>}{preferences && <><p>站内通知可用；邮件和微信外发未接入。</p><div className="ops-checks">{prefs.map(pref=><label key={pref.category}><input type="checkbox" checked={pref.enabled} disabled={busy} onChange={event=>void act(()=>operationsApi.preference({category:pref.category,channel:'in_app',enabled:event.target.checked}))}/>{categories[pref.category]}</label>)}</div></>}
    <div className="ops-pagination"><label><input type="checkbox" checked={unread} onChange={event=>{setUnread(event.target.checked);setPage(1)}}/>仅看未读</label><button disabled={busy} onClick={()=>void act(()=>operationsApi.refreshNotifications())}>获取最新通知</button></div>
    {!data ? <p role="status">正在加载通知…</p> : data.items.length===0 ? <p>暂无通知</p> : <ul className="ops-list">{data.items.map(row=><li key={row.id}><a href={`#${row.url}`}>{row.title}</a><p>{categories[row.category]} · {operationStatus[row.body] || row.body} · {new Date(row.occurred_at).toLocaleString()} · {row.read_at?'已读':'未读'}</p>{!row.read_at && <button disabled={busy} onClick={()=>void act(()=>operationsApi.readNotification(row.id))}>标记已读</button>}</li>)}</ul>}
    <div className="ops-pagination"><button disabled={page<=1} onClick={()=>setPage(v=>v-1)}>上一页通知</button><span>第{page}页 · 共{data?.total || 0}条</span><button disabled={!data || page*10>=data.total} onClick={()=>setPage(v=>v+1)}>下一页通知</button></div>
  </div>
}
