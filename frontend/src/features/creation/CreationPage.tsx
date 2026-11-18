import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../app/AuthContext'
import { navigate, useHashRoute } from '../../app/router'
import { collectionApi, type CollectionTaskOut } from '../../shared/api/collection'
import { creationApi, type CreationOutput, type CreationRule, type CreationTask, type GenerationModel } from '../../shared/api/creation'
import { MaterialSearchPage } from '../materials/MaterialSearchPage'

const labels: Record<string, string> = { pending: '等待中', running: '执行中', insufficient: '条件不足', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const reasons: Record<string, string> = { new_materials_insufficient: '新增素材不足', material_count_insufficient: '素材数量不足', relevance_insufficient: '素材相关度不足', body_unavailable: '素材正文不可用', duplicate_topic: '已有相同主题文章', active_task: '已有进行中的创作任务' }

export function CreationPage() {
  const route = useHashRoute()
  const { hasPermission } = useAuth()
  const writable = hasPermission('creation:write')
  const view = route.query.get('view') || 'topic'
  const taskId = route.query.get('task_id') || ''
  const [tasks, setTasks] = useState<CreationTask[]>([])
  const [rules, setRules] = useState<CreationRule[]>([])
  const [models, setModels] = useState<GenerationModel[]>([])
  const [collections, setCollections] = useState<CollectionTaskOut[]>([])
  const [outputs, setOutputs] = useState<CreationOutput[]>([])
  const [detail, setDetail] = useState<CreationTask | null>(null)
  const [error, setError] = useState('')
  const [trigger, setTrigger] = useState('manual')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<CreationRule | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [taskPage, rulePage] = await Promise.all([creationApi.tasks(), creationApi.rules()])
      setTasks(taskPage.items); setRules(rulePage.items)
      if (taskId) { const [selected, items] = await Promise.all([creationApi.task(taskId), creationApi.outputs(taskId)]); setDetail(selected); setOutputs(items) }
      else { setDetail(null); setOutputs([]) }
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '加载创作记录失败') }
  }, [taskId])

  useEffect(() => {
    if (view === 'topic' || view === 'material') return
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => window.clearInterval(timer)
  }, [view, refresh])
  useEffect(() => {
    if (view !== 'rules' || !writable) return
    void creationApi.models().then(setModels).catch(cause => setError(String(cause)))
    if (hasPermission('collection:read')) void collectionApi.listTasks(1, 100).then(page => setCollections(page.items)).catch(cause => setError(String(cause)))
  }, [view, writable, hasPermission])

  const go = (target: string, id?: string) => navigate('/creation', new URLSearchParams({ view: target, ...(id ? { task_id: id } : {}) }))
  async function action(id: string, name: 'cancel' | 'retry' | 'regenerate') {
    setBusy(true)
    try { const result = await creationApi.action(id, name); if ('resource_id' in result && name === 'regenerate') go('tasks', result.resource_id); else await refresh() }
    catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }
  async function saveRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); const value = (key: string) => String(data.get(key) || '')
    const body = { name: value('name'), topic: value('topic'), trigger_type: value('trigger'),
      trigger_config: { cron: value('trigger') === 'schedule' ? value('cron') : null, timezone: value('timezone') || 'Asia/Shanghai', new_material_threshold: Number(value('threshold')) },
      collection_task_ids: data.getAll('collections').map(String), material_strategy: value('strategy'),
      min_new_material_count: Number(value('min_new')), min_material_count: Number(value('min_material')),
      min_relevance: Number(value('min_relevance')), reference_count: Number(value('references')),
      batch_count: Number(value('batch')), article_type: value('article_type'), writing_style: value('style'),
      min_words: Number(value('min_words')), max_words: Number(value('max_words')),
      model_config_id: value('model'), prompt: value('prompt'), require_analysis: data.get('analysis') === 'on' }
    setBusy(true)
    try { if (editing) await creationApi.changeRule(editing.id, body); else await creationApi.saveRule(body); form.reset(); setEditing(null); setTrigger('manual'); await refresh() }
    catch (cause) { setError(cause instanceof Error ? cause.message : '保存规则失败') }
    finally { setBusy(false) }
  }

  return <section className="list-page"><nav aria-label="创作页面"><button onClick={() => go('topic')}>主题创作</button>{' '}<button onClick={() => go('material')}>素材创作</button>{' '}<button onClick={() => go('rules')}>创作规则</button>{' '}<button onClick={() => go('tasks')}>创作记录</button></nav>
    {view === 'topic' && <MaterialSearchPage topic />}
    {view === 'material' && <MaterialSearchPage key="material" topic materialMode />}
    {error && <p role="alert">{error}</p>}
    {view === 'rules' && <><h1>创作规则</h1><p>目标公众号将在账号管理接入后提供选择。</p>
      {writable && <form key={editing?.id || 'new'} className="collection-form" onSubmit={event => void saveRule(event)}>
        <h2>{editing ? '编辑规则' : '新建规则'}</h2><label>规则名称<input name="name" required defaultValue={editing?.name} /></label><label>主题<input name="topic" defaultValue={editing?.topic} /></label>
        <label>关联采集任务<select name="collections" multiple defaultValue={editing?.collection_task_ids}>{collections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>触发方式<select name="trigger" value={trigger} onChange={e => setTrigger(e.target.value)}><option value="manual">人工</option><option value="collection_completed">采集完成</option><option value="schedule">定时</option><option value="new_material_count">新增素材数量</option></select></label>
        {trigger === 'schedule' && <label>定时 Cron<input name="cron" required placeholder="0 8 * * *" defaultValue={editing?.trigger_config.cron || ''} /></label>}
        <label>时区<input name="timezone" defaultValue={editing?.trigger_config.timezone ?? 'Asia/Shanghai'} /></label><label>新增数量触发阈值<input name="threshold" type="number" min="1" defaultValue={editing?.trigger_config.new_material_threshold ?? 1} /></label>
        <label>素材策略<select name="strategy" defaultValue={editing?.material_strategy ?? 'new_and_unused'}><option value="new_and_unused">新增与历史未使用</option><option value="new_only">仅新增</option><option value="all">全库</option></select></label>
        <label>最低新增数<input name="min_new" type="number" min="0" max="100" defaultValue={editing?.min_new_material_count ?? 1} /></label><label>最低素材数<input name="min_material" type="number" min="1" max="100" defaultValue={editing?.min_material_count ?? 1} /></label>
        <label>最低相关度<input name="min_relevance" type="number" min="0" max="1" step="0.05" defaultValue={editing?.min_relevance ?? 0} /></label><label>每篇引用数<input name="references" type="number" min="1" max="100" defaultValue={editing?.reference_count ?? 3} /></label><label>每批篇数<input name="batch" type="number" min="1" max="20" defaultValue={editing?.batch_count ?? 1} /></label>
        <label>文章类型<input name="article_type" defaultValue={editing?.article_type ?? 'news'} required /></label><label>写作风格<input name="style" defaultValue={editing?.writing_style ?? '客观'} required /></label><label>最少字数<input name="min_words" type="number" min="1" defaultValue={editing?.min_words ?? 300} /></label><label>最多字数<input name="max_words" type="number" min="1" defaultValue={editing?.max_words ?? 1200} /></label>
        <label>生成模型<select name="model" required defaultValue={editing?.model_config_id ?? ''}><option value="">请选择</option>{models.map(model => <option key={model.id} value={model.id}>{model.name}（{model.model_name}）</option>)}</select></label><label>补充要求<textarea name="prompt" defaultValue={editing?.prompt} /></label><label><input type="checkbox" name="analysis" defaultChecked={editing?.require_analysis} />要求当前素材修订分析已完成</label>
        <button type="submit" disabled={busy || !models.length}>保存规则</button>{editing && <button type="button" onClick={() => { setEditing(null); setTrigger('manual') }}>取消编辑</button>}
      </form>}
      {!rules.length && <p>暂无规则。</p>}<ul>{rules.map(rule => <li key={rule.id}><strong>{rule.name}</strong> · {rule.trigger_type} · {rule.material_strategy} · {rule.enabled ? '启用' : '停用'} {writable && <><button onClick={() => { setEditing(rule); setTrigger(rule.trigger_type) }}>编辑</button><button disabled={busy || !rule.enabled} onClick={() => void creationApi.runRule(rule.id, crypto.randomUUID()).then(result => go('tasks', result.resource_id)).catch(cause => setError(String(cause)))}>立即执行</button><button disabled={busy} onClick={() => void creationApi.changeRule(rule.id, { enabled: !rule.enabled }).then(refresh).catch(cause => setError(String(cause)))}>{rule.enabled ? '停用' : '启用'}</button></>}</li>)}</ul>
    </>}
    {view === 'tasks' && <><h1>创作记录</h1>{!tasks.length && <p>暂无创作记录。</p>}<ul>{tasks.map(task => <li key={task.id}><button type="button" onClick={() => go('tasks', task.id)}>{task.topic || '素材创作'}</button> · {labels[task.status] || task.status} · {task.trigger_type} · {new Date(task.created_at).toLocaleString()}</li>)}</ul>
      {detail && <section aria-label="创作任务详情"><h2>{detail.topic || '素材创作'} · {labels[detail.status] || detail.status}</h2><p>触发：{detail.trigger_type} · {detail.trigger_source || '手动请求'}</p>
        {detail.decision?.reasons.length ? <p role="status">条件不足：{detail.decision.reasons.map(reason => reasons[reason] || reason).join('、')}</p> : null}{detail.error_code && <p role="alert">失败原因：{detail.error_code}</p>}
        {detail.decision?.details.retrieval_degraded === true && <p role="status">语义检索暂不可用，已使用关键词检索（{String(detail.decision.details.retrieval_degradation_reason || '服务不可用')}）。</p>}
        {detail.candidates?.length > 0 && <section><h3>候选素材</h3><ul>{detail.candidates.map(item => <li key={item.material_id}><a href={`#/materials?material_id=${item.material_id}`}>{item.material_id}</a> · 修订 {item.revision_id} · {item.selected ? '已采用' : '未采用'}{item.relevance_score != null && ` · 相关度 ${item.relevance_score.toFixed(2)}`}</li>)}</ul></section>}
        {writable && <>{['pending', 'running'].includes(detail.status) && <button disabled={busy} onClick={() => void action(detail.id, 'cancel')}>取消任务</button>}{['failed', 'cancelled'].includes(detail.status) && <button disabled={busy} onClick={() => void action(detail.id, 'retry')}>重试未完成内容</button>}{!['pending', 'running'].includes(detail.status) && <button disabled={busy} onClick={() => void action(detail.id, 'regenerate')}>重新生成</button>}</>}
        {outputs.map(output => <article key={output.id}><h3>{output.title}</h3><p>候选标题：{output.candidate_titles.join('、')}</p><p>摘要：{output.summary}</p><p>大纲：{output.outline.join('；')}</p><pre>{output.body_markdown}</pre><p>关键词：{output.keywords.join('、')}</p><p>封面建议：{output.cover_suggestion}</p><p>素材引用：{output.citations.length}</p><a href={`#/content/articles/${output.article_id}`}>查看待审核文章</a></article>)}
      </section>}
    </>}
  </section>
}
