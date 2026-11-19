import { useEffect, useState } from 'react'
import { navigate, useHashRoute } from '../../app/router'
import { publishingApi, publishLabels, type PublishOrder } from '../../shared/api/wechat'
import type { Page } from '../../shared/api/articles'

export function PublishOrdersPage() {
  const { query } = useHashRoute()
  const page = Math.max(1, Number(query.get('page')) || 1)
  const accountId = query.get('account_id') || undefined
  const [result, setResult] = useState<Page<PublishOrder> | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    setResult(null); setError('')
    void publishingApi.list(undefined, page, accountId).then(value => { if (active) setResult(value) }).catch(cause => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [page, accountId, reload])
  function go(value: number) { navigate('/content/publishing', new URLSearchParams({ page: String(value), ...(accountId ? { account_id: accountId } : {}) })) }
  return <section className="list-page"><h1>发布记录</h1><button onClick={() => navigate('/content')}>返回文章列表</button><button onClick={() => setReload(value => value+1)}>刷新</button>{error && <p role="alert">{error}</p>}{!result && !error && <p role="status">正在加载发布记录…</p>}{result && <>{result.items.length === 0 && <p>暂无发布记录</p>}<div className="table-scroll"><table><thead><tr><th>状态</th><th>账号</th><th>版本</th><th>时间</th><th>操作</th></tr></thead><tbody>{result.items.map(item => <tr key={item.id}><td>{publishLabels[item.status]}</td><td>{item.account_id}</td><td>{item.article_revision_id}</td><td>{new Date(item.scheduled_at || item.created_at).toLocaleString()}</td><td><a href={`#/content/articles/${item.article_id}?order_id=${item.id}`}>查看发布详情</a></td></tr>)}</tbody></table></div><button disabled={page <= 1} onClick={() => go(page-1)}>上一页</button><button disabled={page*20 >= result.total} onClick={() => go(page+1)}>下一页</button></>}</section>
}
