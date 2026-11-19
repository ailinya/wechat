import { useEffect, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { navigate, useHashRoute } from '../../app/router'
import { articleApi, articleStatuses, type ArticleSummary, type Page, type QueueItem } from '../../shared/api/articles'
import { Pagination } from '../../shared/components/Pagination'
import { publishLabels, draftLabels } from '../../shared/api/wechat'

export function ContentPage() {
  const { hasPermission } = useAuth()
  const { query } = useHashRoute()
  const [data, setData] = useState<Page<ArticleSummary> | null>(null)
  const [queue, setQueue] = useState<Page<QueueItem> | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const isQueue = query.get('view') === 'reviews'
  const page = Math.max(1, Number(query.get('page')) || 1)
  const size = Number(query.get('page_size')) || 20
  const search = new URLSearchParams(query)
  search.delete('view'); search.set('page', String(page)); search.set('page_size', String(size))
  search.delete('from_local'); search.delete('to_local')
  const key = search.toString()
  const allowed = !isQueue || hasPermission('article:review')
  useEffect(() => {
    let active = true
    setError(''); setData(null); setQueue(null)
    if (!allowed) return
    const request = isQueue ? articleApi.queue(page).then(result => { if (active) setQueue(result) }) : articleApi.list(key).then(result => { if (active) setData(result) })
    void request.catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '加载失败') })
    return () => { active = false }
  }, [key, page, isQueue, reload, allowed])
  function patch(values: Record<string, string | number>) {
    const next = new URLSearchParams(query)
    for (const [field, value] of Object.entries(values)) { if (value === '') next.delete(field); else next.set(field, String(value)) }
    navigate('/content', next)
  }
  const rows = isQueue ? queue : data
  function open(id: string) { navigate(`/content/articles/${id}`, new URLSearchParams({ list: window.location.hash })) }
  return <section className="list-page">
    <div className="page-heading"><div><h1>内容管理</h1><p>编辑文章、查看引用并完成人工审核。</p></div><div className="form-actions">
      {hasPermission('article:write') && <button onClick={() => navigate('/content/new')}>新建文章</button>}
      <button onClick={() => patch({ view: '', page: 1 })}>文章列表</button>
      {hasPermission('article:review') && <button onClick={() => patch({ view: 'reviews', page: 1 })}>审核队列</button>}
      {hasPermission('publish:read') && <button onClick={() => navigate('/content/publishing')}>发布记录</button>}
    </div></div>
    {!isQueue && <div className="filter-bar">
      <label>文章状态<select value={query.get('status') || ''} onChange={e => patch({ status: e.target.value, page: 1 })}><option value="">全部状态</option>{Object.entries(articleStatuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>创作来源<select value={query.get('origin_type') || ''} onChange={e => patch({ origin_type: e.target.value, page: 1 })}><option value="">全部来源</option><option value="manual">人工</option><option value="generated">AI 创作</option></select></label>
      <label>创建时间起<input type="datetime-local" value={query.get('from_local') || ''} onChange={e => { const value = e.target.value; const next = new URLSearchParams(query); next.set('page', '1'); if (value) { next.set('from_local', value); next.set('created_from', new Date(value).toISOString()) } else { next.delete('from_local'); next.delete('created_from') } navigate('/content', next) }} /></label>
      <label>创建时间止<input type="datetime-local" value={query.get('to_local') || ''} onChange={e => { const value = e.target.value; const next = new URLSearchParams(query); next.set('page', '1'); if (value) { next.set('to_local', value); next.set('created_to', new Date(value).toISOString()) } else { next.delete('to_local'); next.delete('created_to') } navigate('/content', next) }} /></label>
    </div>}
    {!allowed ? <p role="alert">无审核权限</p> : error ? <div role="alert">{error}<button onClick={() => setReload(value => value + 1)}>重试</button></div> : !rows ? <p role="status">正在加载…</p> : <>
      {!rows.items.length ? <p>暂无{isQueue ? '待审核文章' : '文章'}</p> : <div className="table-scroll"><table><thead><tr><th>文章</th><th>版本</th><th>{isQueue ? '提审时间' : '状态'}</th><th>操作</th></tr></thead><tbody>
        {isQueue ? queue?.items.map(row => <tr key={row.article_id}><td>{row.title}</td><td>v{row.version}</td><td>{new Date(row.submitted_at).toLocaleString()}</td><td><button onClick={() => open(row.article_id)}>查看并审核</button></td></tr>) : data?.items.map(row => <tr key={row.id}><td>{row.title}<small> · {row.origin_type === 'manual' ? '人工' : 'AI 创作'} · {row.author}</small></td><td>v{row.version}</td><td>{articleStatuses[row.status]}{Object.entries(row.draft_summary || {}).map(([status, count]) => <small key={`draft-${status}`}> · {draftLabels[status] || status} {count} 条</small>)}{Object.entries(row.publish_summary || {}).map(([status, count]) => <small key={status}> · {publishLabels[status] || status} {count} 单</small>)}</td><td><button onClick={() => open(row.id)}>查看文章</button></td></tr>)}
      </tbody></table></div>}
      <Pagination page={page} pageSize={isQueue ? 20 : size} total={rows.total} onPageChange={value => patch({ page: value })} onPageSizeChange={value => patch({ page_size: value, page: 1 })} />
    </>}
  </section>
}
