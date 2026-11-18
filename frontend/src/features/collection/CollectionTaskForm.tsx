import { useEffect, useState } from 'react'
import { apiRequest } from '../../shared/api/client'
import type { CollectionSourceOut, CollectionTaskOut, CollectionTaskIn } from '../../shared/api/types'
import { useFeedback } from '../../shared/components/feedback'

type Options = { searches: { id: string; name: string }[]; models: { id: string; name: string }[]; sources?: {id:string;name:string}[] }

export function CollectionTaskForm({ sources, task, onSaved, onCancel }: {
  sources: CollectionSourceOut[]; task?: CollectionTaskOut; onSaved: () => void; onCancel: () => void
}) {
  const [mode, setMode] = useState<'source' | 'topic_search'>(task?.mode ?? 'source')
  const [analysis, setAnalysis] = useState(task?.analysis?.enabled ?? false)
  const [options, setOptions] = useState<Options>({ searches: [], models: [] })
  const [busy, setBusy] = useState(false)
  const { notify } = useFeedback()
  const sourceChoices=[...(options.sources ?? sources.filter(v=>v.enabled))]
  for(const source of task?.sources ?? [])if(!sourceChoices.some(v=>v.id===source.id))sourceChoices.push(source)
  useEffect(() => { const controller = new AbortController(); void apiRequest<Options>('/collection/config-options', { signal: controller.signal }).then(setOptions).catch(() => {}); return () => controller.abort() }, [])
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '')
    const payload: CollectionTaskIn = {
      name: value('name'), mode, topic: mode === 'topic_search' ? value('topic') : null,
      source_ids: mode === 'source' ? form.getAll('source').map(String) : [],
      keywords: value('keywords').split(/[,，\n]/).map(v => v.trim()).filter(Boolean),
      allowed_domains: value('domains').split(/[,，\s]+/).filter(Boolean),
      max_candidates: Number(value('max_candidates')), max_fetch: Number(value('max_fetch')), max_pages: Number(value('max_pages')),
      time_range_days: Number(value('days')),
      search_config_id: mode === 'topic_search' ? value('search') || null : null,
      analysis: { enabled: analysis, model_config_id: analysis ? value('model') || null : null, apply_policy: value('policy') as 'suggest_only' | 'fill_empty' },
      schedule: task?.schedule ?? { frequency: 'manual', timezone: 'Asia/Shanghai' },
      auto_materialize: form.has('auto_materialize'), auto_create: task?.auto_create ?? false,
    }
    setBusy(true)
    try { await apiRequest(`/collection/tasks${task ? `/${task.id}` : ''}`, { method: task ? 'PATCH' : 'POST', body: payload }); notify('success', task ? '任务已保存' : '任务已创建'); onSaved() }
    catch (error) { notify('error', error instanceof Error ? error.message : '保存失败') }
    finally { setBusy(false) }
  }
  return <form className="collection-form" onSubmit={save}>
    <label>任务名称<input name="name" aria-label="任务名称" required defaultValue={task?.name} /></label>
    <label>采集模式<select aria-label="采集模式" value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="source">指定来源</option><option value="topic_search">主题搜索</option></select></label>
    {mode === 'topic_search' ? <><label>主题<input name="topic" required defaultValue={task?.topic ?? ''} /></label><label>搜索配置<select name="search" required defaultValue={task?.search_config_id ?? ''}><option value="">选择搜索配置</option>{options.searches.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label></> : <fieldset><legend>采集来源</legend>{sourceChoices.map(v => <label key={v.id}><input name="source" type="checkbox" value={v.id} defaultChecked={task ? task.sources.some(s => s.id === v.id) : true} />{v.name}</label>)}</fieldset>}
    <label>关键词<input name="keywords" defaultValue={task?.keywords.join(', ')} /></label>
    <label>限定网站<input name="domains" defaultValue={task?.allowed_domains?.join(', ')} placeholder="example.com" /></label>
    <label>最近天数<input name="days" type="number" min="1" max="365" defaultValue={task?.time_range_days ?? 7} required /></label>
    <label>候选上限<input name="max_candidates" type="number" min="1" max="100" defaultValue={task?.max_candidates ?? 100} required /></label>
    <label>抓取上限<input name="max_fetch" type="number" min="1" max="100" defaultValue={task?.max_fetch ?? 20} required /></label>
    <label>分页上限<input name="max_pages" type="number" min="1" max="20" defaultValue={task?.max_pages ?? 5} required /></label>
    <label><input type="checkbox" checked={analysis} onChange={e => setAnalysis(e.target.checked)} />LLM 素材分析</label>
    {analysis && <label>分析模型<select name="model" required defaultValue={task?.analysis?.model_config_id ?? ''}><option value="">选择可用分析模型</option>{options.models.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>}
    <label>建议策略<select name="policy" defaultValue={task?.analysis?.apply_policy ?? 'suggest_only'}><option value="suggest_only">仅展示建议</option><option value="fill_empty">补充未人工维护的空字段</option></select></label>
    <label><input name="auto_materialize" type="checkbox" defaultChecked={task?.auto_materialize ?? false} />自动入库</label>
    <div><button className="primary-button" disabled={busy} type="submit">{task ? '保存任务' : '新建任务'}</button>{task && <button type="button" onClick={onCancel}>取消编辑</button>}</div>
  </form>
}
