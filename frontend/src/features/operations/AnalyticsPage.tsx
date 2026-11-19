import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../app/AuthContext'
import { navigate, useHashRoute } from '../../app/router'
import { operationsApi, reportKinds, operationStatus, operationSource, type ReportKind } from '../../shared/api/operations'
import type { ReportOut, ConnectionOut } from '../../shared/api/types'
import { accountsApi, type Account } from '../../shared/api/wechat'
import './operations.css'

const supported: Record<ReportKind,string[]> = { collection:['collection_task_id'], materials:['collection_task_id','creation_task_id'], creation:['collection_task_id','creation_task_id'], reviews:['creation_task_id'], publishing:['account_id','creation_task_id'], accounts:['account_id'] }
const filterLabels: Record<string,string> = { collection_task_id:'采集任务ID', creation_task_id:'创作任务ID', account_id:'公众号' }
const permissions: Record<ReportKind,string> = { collection:'collection:read',materials:'material:read',creation:'creation:read',reviews:'article:read',publishing:'publish:read',accounts:'account:read' }
export function AnalyticsPage() {
  const { hasPermission } = useAuth(), route=useHashRoute()
  const kind = (Object.keys(reportKinds).includes(route.query.get('kind') || '') ? route.query.get('kind') : 'collection') as ReportKind
  const page=Math.max(1,Number(route.query.get('page')) || 1)
  const query=new URLSearchParams(route.query);query.delete('kind');query.set('page',String(page));query.set('page_size','20')
  const key=query.toString()
  const [result,setResult]=useState<{key:string;kind:ReportKind;value:ReportOut}|null>(null),[accounts,setAccounts]=useState<Account[]>([])
  const data=result?.key===key && result.kind===kind?result.value:null
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0)
  const canRead=hasPermission(permissions[kind] as Parameters<typeof hasPermission>[0])
  useEffect(()=>{if(!canRead)return;let live=true;void operationsApi.report(kind,new URLSearchParams(key)).then(value=>{if(live){setResult({key,kind,value});setError('')}}).catch(cause=>{if(live){setResult(null);setError(cause.message)}});return()=>{live=false}},[kind,key,canRead,refresh])
  useEffect(()=>{if(!hasPermission('account:read'))return;let live=true;void accountsApi.list().then(value=>{if(live)setAccounts(value.items)}).catch(()=>{});return()=>{live=false}},[hasPermission])
  function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();const form=new FormData(event.currentTarget),q=new URLSearchParams({kind});for(const [name,value]of form){if(String(value))q.set(name,String(value))}navigate('/analytics',q)}
  async function act(work:()=>Promise<ConnectionOut|void>){setBusy(true);setError('');setMessage('');try{const result=await work();if(result)setMessage(result.reason);setRefresh(v=>v+1)}catch(cause){setError(cause instanceof Error?cause.message:'操作失败')}finally{setBusy(false)}}
  function changeKind(value:string){navigate('/analytics',new URLSearchParams({kind:value,...Object.fromEntries(['start_date','end_date','timezone'].filter(k=>route.query.has(k)).map(k=>[k,route.query.get(k)!]))}))}
  return <section className="operations-page"><header className="page-header"><div><h1>数据统计分析</h1><p>业务报表、统计口径与公众号可用指标</p></div><button onClick={()=>setRefresh(v=>v+1)}>刷新报表</button></header>
    <label>数据类型<select value={kind} onChange={event=>changeKind(event.target.value)}>{Object.entries(reportKinds).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
    <form key={kind+key} className="ops-card ops-filters" onSubmit={submit}><label>开始日期<input type="date" name="start_date" defaultValue={route.query.get('start_date') || ''}/></label><label>结束日期（不含当天）<input type="date" name="end_date" defaultValue={route.query.get('end_date') || ''}/></label><label>统计时区<input name="timezone" defaultValue={route.query.get('timezone') || 'Asia/Shanghai'} required/></label>
      {supported[kind].map(name=><label key={name}>{filterLabels[name]}{name==='account_id'?<select name={name} defaultValue={route.query.get(name)||''}><option value="">全部公众号</option>{accounts.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select>:<input name={name} defaultValue={route.query.get(name)||''} placeholder="可选：任务UUID"/>}</label>)}<button>应用筛选</button><button type="button" onClick={()=>navigate('/analytics',new URLSearchParams({kind}))}>重置筛选</button>
    </form>
    {!canRead && <p role="alert">没有该数据类型的业务读取权限</p>}{error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {canRead && !data && !error && <p role="status">正在加载统计…</p>}
    {canRead && data && <><div className="ops-metrics">{[['明细记录数',data.total],[{collection:'采集结果数',materials:'素材条数',creation:'产出文章数',reviews:'审核记录数',publishing:'交付及发布记录数',accounts:'快照及占位记录数'}[kind],data.summary.quantity],['成功率',data.summary.success_rate==null?'不适用':`${(data.summary.success_rate*100).toFixed(1)}%`],['成功率分母',data.summary.denominator],['尝试次数',data.summary.attempts],['复用素材数',data.summary.reused_materials]].map(([label,value])=><article className="ops-metric" key={label}><span>{label}</span><strong>{value}</strong></article>)}</div><p className="ops-muted">区间：{data.filters.start_date} 至 {data.filters.end_date}（不含），{data.filters.timezone}。{data.summary.definition}</p>
      <section className="ops-card"><h2>每日记录趋势</h2>{data.trend.length ? <figure><div className="ops-chart" role="img" aria-label="每日记录数量柱状图">{data.trend.map(point=><div className="ops-bar" key={point.day} title={`${point.day}：${point.count}条`}><span>{point.count}</span><i style={{height:`${point.count/Math.max(...data.trend.map(x=>x.count),1)*120}px`}}/><span>{point.day.slice(5)}</span></div>)}</div><figcaption className="ops-muted">按声明时区的日期分组，数量与明细一致。</figcaption></figure>:<p>当前区间暂无记录</p>}</section>
      <div className="ops-columns">{[['状态分布',data.summary.by_status],['来源分布',data.summary.by_source],['任务／规则／账号表现',data.summary.by_group],['失败原因',data.summary.failure_reasons]].map(([title,values])=><section className="ops-card" key={String(title)}><h2>{String(title)}</h2>{Object.keys(values).length?<ul className="ops-list">{Object.entries(values).map(([label,value])=><li key={label}>{operationStatus[label] || operationSource[label] || label || '未分组'}：{value}</li>)}</ul>:<p>暂无数据</p>}</section>)}</div>
      <section className="ops-card"><div className="page-header"><h2>报表明细</h2>{hasPermission('analytics:export') && <button disabled={busy} onClick={()=>void act(()=>{const q=new URLSearchParams(key);q.delete('page');q.delete('page_size');return operationsApi.export(kind,q)})}>导出当前筛选全部CSV</button>}</div>
        {!data.items.length?<p>暂无符合条件的数据</p>:<div className="ops-scroll"><table><thead><tr><th>记录</th><th>结果</th><th>来源</th><th>归属时间</th><th>尝试／数量／引用</th>{kind==='accounts'&&<><th>阅读</th><th>点赞</th><th>分享</th><th>采集时间</th></>}</tr></thead><tbody>{data.items.map(row=><tr key={row.id}><td><a href={`#${row.url}`}>{row.title || '未命名'}</a>{row.reason&&<p>{row.reason}</p>}</td><td>{operationStatus[row.status]||row.status}</td><td>{operationSource[row.source]||row.source}</td><td>{new Date(row.occurred_at).toLocaleString('zh-CN',{timeZone:data.filters.timezone})}</td><td>{row.attempts}／{row.quantity}／{row.reference_count}</td>{kind==='accounts'&&<>{['reads','likes','shares'].map(name=><td key={name} title={row.metrics?.[name]?.reason || ''}>{row.metrics?.[name]?.available?row.metrics[name].value:'不可用'}</td>)}<td>{row.collected_at?new Date(row.collected_at).toLocaleString():'尚未采集'}</td></>}</tr>)}</tbody></table></div>}
        <div className="ops-pagination"><button disabled={page<=1} onClick={()=>{const q=new URLSearchParams(route.query);q.set('page',String(page-1));navigate('/analytics',q)}}>上一页报表</button><span>第{page}页 · 共{data.total}条</span><button disabled={page*20>=data.total} onClick={()=>{const q=new URLSearchParams(route.query);q.set('page',String(page+1));navigate('/analytics',q)}}>下一页报表</button></div>
      </section>
    </>}
    {kind==='accounts'&&hasPermission('account:write')&&<form className="ops-card ops-filters" onSubmit={event=>{event.preventDefault();const form=new FormData(event.currentTarget);void act(()=>operationsApi.metrics(String(form.get('account')),String(form.get('date'))))}}><h2>只读采集微信指标</h2><label>指标公众号<select name="account" required><option value="">请选择</option>{accounts.filter(a=>a.status==='active').map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label>群发日期（北京昨日或此前7天）<input type="date" name="date" required/></label><button disabled={busy}>读取实际可用指标</button><p>仅针对群发图文的累计数据；无权限、无数据和缺失字段显示不可用。</p></form>}
  </section>
}
