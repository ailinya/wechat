import { useEffect, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { operationsApi, operationStatus } from '../../shared/api/operations'
import type { DashboardOut, DashboardLink, PlatformPublic } from '../../shared/api/types'
import { NotificationsPanel } from '../operations/NotificationsPanel'
import '../operations/operations.css'

const labels: Record<string,string> = { collected_today:'今日采集结果', materials_total:'素材总数', materials_today:'今日新增素材', ai_articles:'AI生成文章', pending_review:'待审核文章', published_articles:'已发布文章', publish_failed:'接口发布失败', drafts_awaiting_manual:'已同步待手动发布' }
function Links({ items }: { items: DashboardLink[] }) { return items.length ? <ul className="ops-list">{items.map((item,index) => <li key={`${item.id}-${index}`}><a href={`#${item.url}`}>{item.title || '未命名任务'}</a><p>{operationStatus[item.status] || item.status} · {new Date(item.occurred_at).toLocaleString()}{item.reason && ` · ${item.reason}`}{!!item.account_names?.length && ` · ${item.account_names.join('、')}`}</p></li>)}</ul> : <p className="ops-muted">暂无记录</p> }

export function DashboardHome() {
  const { user, hasPermission } = useAuth()
  const [data,setData] = useState<DashboardOut | null>(null)
  const [platform,setPlatform] = useState<PlatformPublic | null>(null)
  const [error,setError] = useState('')
  const [refresh,setRefresh] = useState(0)
  useEffect(() => { let live=true; void Promise.all([operationsApi.dashboard(),operationsApi.publicPlatform()]).then(([value,p])=>{if(live){setData(value);setPlatform(p);setError('')}}).catch(cause=>{if(live)setError(cause.message)});return()=>{live=false} },[refresh])
  const shortcuts = [{permission:'collection:write',url:'/collection',label:'配置采集任务'}, {permission:'collection:run',url:'/collection',label:'立即采集'}, {permission:'creation:write',url:'/creation',label:'开始AI创作'}, {permission:'article:write',url:'/content/new',label:'新建文章'}, {permission:'material:write',url:'/materials',label:'上传素材'}, {permission:'account:write',url:'/accounts',label:'绑定公众号'}]
  return <section className="operations-page"><header className="page-header"><div><h1>{platform?.name || '工作台'}</h1><p>你好，{user?.name}。{platform?.description}</p>{data && <p className="ops-muted">{new Date(data.as_of).toLocaleString('zh-CN',{timeZone:data.timezone})} · {data.timezone}</p>}</div><button onClick={()=>setRefresh(v=>v+1)}>刷新工作台</button></header>
    {error && <p role="alert">{error}</p>}{!data && !error && <p role="status">正在加载运营概览…</p>}
    {data && <><div className="ops-metrics">{Object.entries(data.counters).filter(([,value])=>value!==null).map(([key,value])=><article className="ops-metric" key={key}><span>{labels[key] || key}</span><strong>{value}</strong></article>)}</div><p className="ops-muted">数据来自当前业务记录；草稿同步不计为已发布，今日以 {data.timezone} 为准。</p>
      <section className="ops-card"><h2>快捷操作</h2><div className="ops-tabs">{shortcuts.filter(item=>hasPermission(item.permission as Parameters<typeof hasPermission>[0])).map(item=><a key={item.label} href={`#${item.url}`}>{item.label}</a>)}</div></section>
      <div className="ops-columns"><section className="ops-card"><h2>待办事项</h2><Links items={data.todos}/></section><section className="ops-card"><h2>异常提醒</h2><Links items={data.alerts}/></section><section className="ops-card"><h2>最新文章</h2><Links items={data.recent_articles}/></section><section className="ops-card"><h2>任务运行动态</h2><Links items={data.activity}/></section></div></>}
    <section className="ops-card"><h2>我的站内通知</h2><NotificationsPanel preferences /></section>
  </section>
}
