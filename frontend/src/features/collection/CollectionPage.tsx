/** Collection management page (task 3.9).
 *
 * Four URL-backed sub-views (tasks/sources/runs/results) with real API data,
 * immediate run, bulk materialize, retry/ignore, and links from results to
 * the real material created. Filters/pagination live in the URL so refresh
 * and browser back restore state.
 */

import { useEffect,useState } from 'react'
import { CollectionTaskForm } from './CollectionTaskForm'
import { AnalysisPanel } from './AnalysisPanel'
import { RunCandidates } from './RunCandidates'

import { navigate, useHashRoute } from '../../app/router'
import { collectionApi } from '../../shared/api/collection'
import { apiRequest } from '../../shared/api/client'
import { ApiError } from '../../shared/api/client'
import type {
  CollectionResultOut,
  CollectionRunOut,
  CollectionSourceOut,
  CollectionTaskOut,
} from '../../shared/api/types'
import { DataTable, type Column } from '../../shared/components/DataTable'
import { useFeedback } from '../../shared/components/feedback'
import { Pagination } from '../../shared/components/Pagination'
import { ListStates } from '../../shared/components/states'
import { useListView } from '../../shared/components/useListView'
import { useUrlQuery } from '../../shared/components/useUrlQuery'

type View = 'tasks' | 'sources' | 'runs' | 'results'

const VIEWS: { key: View; label: string }[] = [
  { key: 'tasks', label: '采集任务' },
  { key: 'sources', label: '采集来源' },
  { key: 'runs', label: '执行记录' },
  { key: 'results', label: '采集结果' },
]

const taskColumns: Column<CollectionTaskOut>[] = [
  { key: 'name', header: '任务名称' },
  { key: 'status', header: '状态' },
  {
    key: 'sources',
    header: '来源',
    render: (row) => row.sources.map((source) => source.name).join('、') || '—',
  },
  { key: 'schedule', header: '调度', render: (row) => row.schedule.frequency ?? 'manual' },
  {
    key: 'auto_materialize',
    header: '自动入库',
    render: (row) => (row.auto_materialize ? '是' : '否'),
  },
]

const sourceColumns: Column<CollectionSourceOut>[] = [
  { key: 'name', header: '来源名称' },
  { key: 'source_type', header: '类型' },
  { key: 'base_url', header: '地址' },
  { key: 'status', header: '状态' },
  {
    key: 'enabled',
    header: '启用',
    render: (row) => (row.enabled ? '是' : '否'),
  },
]

const runColumns: Column<CollectionRunOut>[] = [
  { key: 'id', header: '运行 ID', render: (row) => row.id.slice(0, 8) },
  { key: 'trigger', header: '触发' },
  { key: 'status', header: '状态' },
  { key:'end_reason',header:'结束原因',render:row=>row.end_reason??'—' },
  { key:'discovered_count',header:'发现',render:row=>String(row.discovered_count??0) },
  { key: 'fetched_count', header: '抓取', render: (row) => String(row.fetched_count ?? 0) },
  { key: 'parsed_count', header: '解析', render: (row) => String(row.parsed_count ?? 0) },
  { key:'analyzed_count',header:'分析',render:row=>String(row.analyzed_count??0) },
  { key:'review_required_count',header:'待筛选',render:row=>String(row.review_required_count??0) },
  { key:'filtered_count',header:'已过滤',render:row=>String(row.filtered_count??0) },
  { key: 'failed_count', header: '失败', render: (row) => String(row.failed_count ?? 0) },
  {
    key: 'error',
    header: '失败原因',
    render: (row) => row.error ?? '—',
  },
]

const resultColumns: Column<CollectionResultOut>[] = [
  { key: 'title', header: '标题' },
  { key: 'parse_status', header: '解析' },
  { key: 'materialize_status', header: '入库' },
  {
    key: 'error',
    header: '失败原因',
    render: (row) => row.error ?? '—',
  },
]

function errorMessage(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : '操作失败，请稍后重试'
}

export function CollectionPage() {
  const route = useHashRoute()
  const patchQuery = useUrlQuery(route.path, route.query)
  const notify = useFeedback().notify

  const view = (VIEWS.find((item) => item.key === route.query.get('view'))?.key ?? 'tasks') as View
  const page = Math.max(1, Number(route.query.get('page')) || 1)
  const pageSize = 10
  const taskId = route.query.get('task_id') ?? undefined
  const runId = route.query.get('run_id') ?? undefined

  const [sourceName, setSourceName] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [editingSource, setEditingSource] = useState<CollectionSourceOut>()
  const [editingTask, setEditingTask] = useState<CollectionTaskOut | undefined>()
  const [analysisResultId, setAnalysisResultId] = useState<string>()
  const [checked, setChecked] = useState<Set<string>>(new Set())

  const sources = useListView<CollectionSourceOut>('/collection/sources', {
    page, pageSize, params: {},
  })
  const tasks = useListView<CollectionTaskOut>('/collection/tasks', { page, pageSize, params: {} })
  const runs = useListView<CollectionRunOut>('/collection/runs', {
    page, pageSize, params: { task_id: taskId },
  })
  const results = useListView<CollectionResultOut>('/collection/results', {
    page, pageSize, params: { run_id: runId },
  })
  useEffect(()=>{
    if(view!=='runs'||!runs.data?.items.some(row=>row.status==='running'||row.status==='pending'))return
    const timer=setInterval(runs.retry,4000)
    return ()=>clearInterval(timer)
  },[view,runs.data,runs.retry])

  function switchView(next: View) {
    setChecked(new Set())
    patchQuery({ view: next === 'tasks' ? null : next, page: null, task_id: null, run_id: null })
  }

  async function createSource(event: React.FormEvent) {
    event.preventDefault()
    const form=new FormData(event.currentTarget as HTMLFormElement)
    try {
      const payload = {
        name: sourceName, source_type: form.get('source_type') as 'rss'|'web_page', base_url: sourceUrl,
        page_kind: form.get('page_kind') as 'article'|'list', article_link_selector: String(form.get('article_link_selector') || '') || null,
        next_page_selector: String(form.get('next_page_selector') || '') || null,
        description: editingSource?.description ?? '', enabled: editingSource?.enabled ?? true,
      }
      if (editingSource) await apiRequest(`/collection/sources/${editingSource.id}`,{method:'PATCH',body:payload})
      else await collectionApi.createSource(payload)
      notify('success', '来源已创建')
      setSourceName('')
      setSourceUrl('')
      setEditingSource(undefined)
      sources.retry()
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function actOnTask(task: CollectionTaskOut, action: 'run' | 'pause' | 'resume') {
    try {
      if (action === 'run') {
        await collectionApi.runTask(task.id)
        notify('success', '任务已受理，执行中')
        switchView('runs')
      } else if (action === 'pause') {
        await collectionApi.pauseTask(task.id)
        notify('success', '任务已暂停')
        tasks.retry()
      } else {
        await collectionApi.resumeTask(task.id)
        notify('success', '任务已恢复')
        tasks.retry()
      }
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function actOnResult(result: CollectionResultOut, action: 'materialize' | 'retry' | 'ignore') {
    try {
      if (action === 'materialize') {
        await collectionApi.materialize(result.id)
        notify('success', '入库已受理')
      } else if (action === 'retry') {
        await collectionApi.retryParse(result.id)
        notify('success', '解析重试已受理')
      } else {
        await collectionApi.ignoreResult(result.id)
        notify('success', '结果已忽略')
      }
      results.retry()
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function bulkMaterialize() {
    if (!checked.size) {
      notify('error', '请先勾选要入库的结果')
      return
    }
    try {
      const outcome = await collectionApi.bulkMaterialize([...checked])
      notify('success', `入库完成：成功 ${outcome.counts.materialized ?? 0}，重复 ${outcome.counts.duplicate ?? 0}，失败 ${outcome.counts.failed ?? 0}`)
      setChecked(new Set())
      results.retry()
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  return (
    <section className="list-page" aria-label="采集管理">
      <h1>采集管理</h1>
      <nav className="sub-nav" aria-label="采集子模块">
        {VIEWS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`sub-nav-item${view === item.key ? ' active' : ''}`}
            aria-current={view === item.key ? 'page' : undefined}
            onClick={() => switchView(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {view === 'sources' && (
        <>
          <form key={editingSource?.id ?? 'new'} className="list-filters" onSubmit={createSource}>
            <input aria-label="来源名称" placeholder="来源名称" value={sourceName}
              onChange={(event) => setSourceName(event.target.value)} required />
            <input aria-label="来源地址" placeholder="https://example.com/feed" value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)} required />
            <select name="source_type" aria-label="来源类型" defaultValue={editingSource?.source_type ?? 'web_page'}><option value="web_page">网页</option><option value="rss">RSS</option></select>
            <select name="page_kind" aria-label="页面类型" defaultValue={editingSource?.page_kind ?? 'article'}><option value="article">文章页</option><option value="list">栏目页</option></select>
            <input name="article_link_selector" aria-label="文章链接选择器" placeholder="文章链接选择器" defaultValue={editingSource?.article_link_selector ?? ''} />
            <input name="next_page_selector" aria-label="下一页选择器" placeholder="下一页选择器" defaultValue={editingSource?.next_page_selector ?? ''} />
            <button type="submit" className="primary-button">{editingSource ? '保存来源' : '新增来源'}</button>
          </form>
          {sources.status === 'ready' && sources.data && (
            <DataTable columns={sourceColumns} rows={sources.data.items} rowKey={(row) => row.id} caption="采集来源" actions={row=><><button type="button" onClick={()=>{setEditingSource(row);setSourceName(row.name);setSourceUrl(row.base_url)}}>编辑来源</button><button type="button" onClick={()=>{void collectionApi.testSource(row.id).then(result=>notify(result.reachable?'success':'error',result.reachable?'连接正常':result.error??'连接失败')).catch(error=>notify('error',String(error)))}}>测试连接</button></>} />
          )}
          <ListStates status={sources.status} error={sources.error} emptyText="还没有采集来源"
            onRetry={sources.status === 'error' ? sources.retry : undefined} />
        </>
      )}

      {view === 'tasks' && (
        <>
          <CollectionTaskForm key={editingTask?.id ?? 'new'} sources={sources.data?.items ?? []} task={editingTask} onCancel={() => setEditingTask(undefined)} onSaved={() => { setEditingTask(undefined); tasks.retry() }} />
          {tasks.status === 'ready' && tasks.data && (
            <>
              <DataTable
                columns={taskColumns}
                rows={tasks.data.items}
                rowKey={(row) => row.id}
                caption="采集任务"
                actions={(row) => (
                  <>
                    <button type="button" className="ghost-button" onClick={() => setEditingTask(row)}>编辑任务</button>
                    <button type="button" className="ghost-button" onClick={() => void actOnTask(row, 'run')}>立即执行</button>
                    {row.status === 'active' ? (
                      <button type="button" className="ghost-button" onClick={() => void actOnTask(row, 'pause')}>暂停</button>
                    ) : (
                      <button type="button" className="ghost-button" onClick={() => void actOnTask(row, 'resume')}>恢复</button>
                    )}
                    <button type="button" className="ghost-button"
                      onClick={() => patchQuery({ view: 'runs', task_id: row.id, page: null })}>
                      执行记录
                    </button>
                  </>
                )}
              />
              <Pagination page={tasks.data.page} pageSize={tasks.data.page_size} total={tasks.data.total}
                onPageChange={(next) => patchQuery({ page: next === 1 ? null : next })}
                onPageSizeChange={() => undefined} />
            </>
          )}
          <ListStates status={tasks.status} error={tasks.error} emptyText="还没有采集任务"
            onRetry={tasks.status === 'error' ? tasks.retry : undefined} />
        </>
      )}

      {view === 'runs' && (
        <>
          {runs.status === 'ready' && runs.data && (
            <>
              <DataTable
                columns={runColumns}
                rows={runs.data.items}
                rowKey={(row) => row.id}
                caption="执行记录"
                actions={(row) => (
                  <button type="button" className="ghost-button"
                    onClick={() => patchQuery({ view: 'results', run_id: row.id, page: null })}>
                    查看结果
                  </button>
                )}
              />
              <Pagination page={runs.data.page} pageSize={runs.data.page_size} total={runs.data.total}
                onPageChange={(next) => patchQuery({ page: next === 1 ? null : next })}
                onPageSizeChange={() => undefined} />
            </>
          )}
          <ListStates status={runs.status} error={runs.error} emptyText="还没有执行记录"
            onRetry={runs.status === 'error' ? runs.retry : undefined} />
        </>
      )}

      {view === 'results' && (
        <>
          {runId && <RunCandidates runId={runId} />}
          {analysisResultId && <AnalysisPanel resultId={analysisResultId} />}
          <div className="list-filters">
            <button type="button" className="primary-button" onClick={() => void bulkMaterialize()}>批量入库</button>
            <span>已勾选 {checked.size} 项</span>
          </div>
          {results.status === 'ready' && results.data && (
            <>
              <DataTable
                columns={resultColumns}
                rows={results.data.items}
                rowKey={(row) => row.id}
                caption="采集结果"
                selection={{
                  checked,
                  onToggle: (id) => setChecked((current) => {
                    const next = new Set(current)
                    if (next.has(id)) next.delete(id)
                    else next.add(id)
                    return next
                  }),
                }}
                actions={(row) => (
                  <>
                    <button type="button" className="ghost-button" onClick={() => setAnalysisResultId(row.id)}>分析详情</button>
                    {row.material_id ? (
                      <button type="button" className="ghost-button"
                        onClick={() => navigate(`/materials/${row.material_id}`)}>
                        查看素材
                      </button>
                    ) : (
                      <button type="button" className="ghost-button"
                        onClick={() => void actOnResult(row, 'materialize')}>入库</button>
                    )}
                    {row.parse_status === 'failed' && (
                      <button type="button" className="ghost-button"
                        onClick={() => void actOnResult(row, 'retry')}>重试解析</button>
                    )}
                    {row.materialize_status === 'pending' && (
                      <button type="button" className="ghost-button"
                        onClick={() => void actOnResult(row, 'ignore')}>忽略</button>
                    )}
                  </>
                )}
              />
              <Pagination page={results.data.page} pageSize={results.data.page_size} total={results.data.total}
                onPageChange={(next) => patchQuery({ page: next === 1 ? null : next })}
                onPageSizeChange={() => undefined} />
            </>
          )}
          <ListStates status={results.status} error={results.error} emptyText="还没有采集结果"
            onRetry={results.status === 'error' ? results.retry : undefined} />
        </>
      )}
    </section>
  )
}
