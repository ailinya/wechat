import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../app/AuthContext'
import { materialsApi, type SearchItem, type SearchRequest, type SearchResponse } from '../../shared/api/materials'
import { creationApi, type GenerationModel } from '../../shared/api/creation'
import { navigate } from '../../app/router'

interface SavedSearch {
  query: string
  scope: 'current' | 'all'
  mode: 'hybrid' | 'keyword_only'
  status: string
  from: string
  to: string
  top: number
  min: number
  response: SearchResponse | null
  selected: SearchItem[]
}

const initial: SavedSearch = { query: '', scope: 'current', mode: 'hybrid', status: '', from: '', to: '', top: 20, min: 0, response: null, selected: [] }

export function MaterialSearchPage({ topic = false, materialMode = false }: { topic?: boolean; materialMode?: boolean }) {
  const { hasPermission, user } = useAuth()
  const storageKey = `${topic ? (materialMode ? 'material-creation-search-v1' : 'topic-material-search-v1') : 'material-search-v1'}:${user?.id ?? 'anonymous'}`
  const [state, setState] = useState<SavedSearch>(() => {
    try { return { ...initial, ...JSON.parse(sessionStorage.getItem(storageKey) || '{}') } }
    catch { return initial }
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [models, setModels] = useState<GenerationModel[]>([])
  const [modelId, setModelId] = useState('')
  useEffect(() => { sessionStorage.setItem(storageKey, JSON.stringify(state)) }, [state, storageKey])
  useEffect(() => {
    if (!topic || !hasPermission('creation:write')) return
    let active = true
    void creationApi.models().then(rows => { if (active) { setModels(rows); setModelId(rows[0]?.id ?? '') } }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '无法加载生成模型') })
    return () => { active = false }
  }, [topic, hasPermission])
  const update = (patch: Partial<SavedSearch>) => setState(current => ({ ...current, ...patch }))

  async function search(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const request: SearchRequest = { query: state.query, scope: state.scope, keyword_mode: state.mode, top_k: state.top, min_relevance: state.min }
      if (state.status) request.statuses = [state.status]
      if (state.from) request.from = new Date(`${state.from}T00:00:00`).toISOString()
      if (state.to) request.to = new Date(`${state.to}T23:59:59`).toISOString()
      const response = await materialsApi.search(request)
      setState(current => ({ ...current, response }))
    } catch (cause) { setError(cause instanceof Error ? cause.message : '检索失败，请重试') }
    finally { setBusy(false) }
  }

  function toggle(item: SearchItem) {
    setState(current => ({ ...current, selected: current.selected.some(x => x.material_id === item.material_id)
      ? current.selected.filter(x => x.material_id !== item.material_id)
      : [...current.selected, item] }))
  }

  async function submitCreation() {
    setBusy(true); setError('')
    try {
      const result = await creationApi.create({ mode: materialMode ? 'material' : 'topic', topic: materialMode ? '' : state.query, model_config_id: modelId,
        materials: state.selected.map(item => ({ material_id: item.material_id, revision_id: item.matched_revision_id })) }, crypto.randomUUID())
      navigate('/creation', new URLSearchParams({ view: 'tasks', task_id: result.resource_id }))
    } catch (cause) { setError(cause instanceof Error ? cause.message : '提交失败') }
    finally { setBusy(false) }
  }

  if (!hasPermission('material:search')) return <p role="alert">当前账号没有素材检索权限。</p>
  return <section className="list-page" aria-label={topic ? '主题创作素材预览' : '素材高级搜索'}>
    <h1>{topic ? (materialMode ? '素材创作：选择素材' : '主题创作：选择素材') : '素材高级搜索'}</h1>
    <p>按主题或关键词检索当前正文，可选择全库以补充已使用的历史素材。</p>
    <form onSubmit={search}>
      <label>{topic && !materialMode ? '创作主题' : '关键词'} <input required maxLength={500} value={state.query} onChange={e => update({ query: e.target.value })} /></label>{' '}
      <label>范围 <select value={state.scope} onChange={e => update({ scope: e.target.value as SavedSearch['scope'] })}><option value="current">当前素材</option><option value="all">全库（包含已使用）</option></select></label>{' '}
      <label>检索方式 <select value={state.mode} onChange={e => update({ mode: e.target.value as SavedSearch['mode'] })}><option value="hybrid">关键词与语义</option><option value="keyword_only">仅关键词</option></select></label>{' '}
      <label>状态 <select value={state.status} onChange={e => update({ status: e.target.value })}><option value="">全部可用状态</option><option value="pending_review">待筛选</option><option value="ready_to_use">待使用</option><option value="partially_used">部分使用</option><option value="used">已使用</option><option value="duplicate">重复素材</option></select></label>{' '}
      <label>发布时间从 <input type="date" value={state.from} onChange={e => update({ from: e.target.value })} /></label>{' '}
      <label>至 <input type="date" value={state.to} onChange={e => update({ to: e.target.value })} /></label>{' '}
      <label>相关度下限 <input type="number" min="0" max="1" step="0.05" value={state.min} onChange={e => update({ min: Number(e.target.value) })} /></label>{' '}
      <label>数量 <input type="number" min="1" max="100" value={state.top} onChange={e => update({ top: Number(e.target.value) })} /></label>{' '}
      <button type="submit" disabled={busy}>{busy ? '检索中…' : '检索'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {state.response?.degraded && <p role="status">语义检索暂不可用，已使用关键词检索（{state.response.degradation_reason}）。</p>}
    {state.response && <section aria-label="检索结果"><h2>检索结果（{state.response.items.length}）</h2>
      {!state.response.items.length && <p>没有符合条件的素材，请调整关键词或筛选条件。</p>}
      <ul>{state.response.items.map(item => <li key={item.material_id}>
        {topic && <label><input type="checkbox" checked={state.selected.some(x => x.material_id === item.material_id)} onChange={() => toggle(item)} />选择</label>}{' '}
        <strong>{item.title}</strong> · 相关度 {item.relevance_score.toFixed(2)} · {item.usage_status}<br />
        {item.snippet}<br />来源：{item.source.title || item.source.type}{item.source.url && /^https?:\/\//i.test(item.source.url) && <> · <a href={item.source.url} target="_blank" rel="noreferrer">查看来源</a></>}
        {item.published_at && <> · {new Date(item.published_at).toLocaleDateString()}</>}
      </li>)}</ul>
    </section>}
    {topic && <section aria-label="已选择素材"><h2>已选择素材（{state.selected.length}）</h2>
      <ul>{state.selected.map(item => <li key={item.material_id}>{item.title} · 修订 {item.matched_revision_id} <button type="button" onClick={() => toggle(item)}>移除</button></li>)}</ul>
      <p>主题和选择保留在当前浏览器会话中。</p>
      {hasPermission('creation:write') && <><label>生成模型 <select value={modelId} onChange={e => setModelId(e.target.value)}><option value="">请选择模型</option>{models.map(model => <option value={model.id} key={model.id}>{model.name}（{model.model_name}）</option>)}</select></label>{' '}
        <button type="button" disabled={busy || !modelId || !state.query.trim() || !state.selected.length} onClick={() => void submitCreation()}>提交创作</button></>}
      {!models.length && hasPermission('creation:write') && <p>暂无可用生成模型，请联系管理员配置。</p>}
    </section>}
  </section>
}
