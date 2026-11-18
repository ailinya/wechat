import { useEffect, useState } from 'react'
import { apiRequest } from '../../shared/api/client'
import type { AnalysisResultOut, MaterialDetailOut, PaginatedResponse_AnalysisResultOut_ } from '../../shared/api/types'
import { useFeedback } from '../../shared/components/feedback'

export function AnalysisPanel({ resultId, materialId }: { resultId?: string; materialId?: string }) {
  const [rows, setRows] = useState<AnalysisResultOut[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [metadata, setMetadata] = useState<Record<string, number>>({})
  const [categories,setCategories]=useState<{id:string;name:string}[]>([])
  const [tags,setTags]=useState<{id:string;name:string}[]>([])
  const [chosenCategory,setChosenCategory]=useState<Record<string,string>>({})
  const [chosenTags,setChosenTags]=useState<Record<string,string[]>>({})
  const [version, setVersion] = useState(0)
  const [reason, setReason] = useState('')
  const { notify } = useFeedback()
  useEffect(()=>{
    const controller=new AbortController()
    void apiRequest<{id:string;name:string}[]>('/materials/categories',{signal:controller.signal}).then(data=>setCategories(Array.isArray(data)?data:[])).catch(()=>{})
    void apiRequest<{id:string;name:string}[]>('/materials/tags',{signal:controller.signal}).then(data=>setTags(Array.isArray(data)?data:[])).catch(()=>{})
    return ()=>controller.abort()
  },[])
  useEffect(() => {
    const controller = new AbortController(); setLoading(true)
    void apiRequest<PaginatedResponse_AnalysisResultOut_>(`/collection/analysis?${new URLSearchParams(resultId ? { result_id: resultId } : { material_id: materialId ?? '' })}`, { signal: controller.signal })
      .then(async data => { setRows(data.items); const versions: Record<string, number> = {}; for (const row of data.items) { if (row.material_id) { const material = await apiRequest<MaterialDetailOut>(`/materials/${row.material_id}`, { signal: controller.signal }); versions[row.id] = material.metadata_version ?? 1 } }; setMetadata(versions); setError('') }).catch(error => { if (!controller.signal.aborted) setError(String(error)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [resultId, materialId, version])
  async function act(row: AnalysisResultOut, action: 'retry' | 'apply' | 'category' | 'tags') {
    try {
      if (action !== 'retry') {
        if (!row.material_id) throw new Error('请先将结果保留为素材')
        await apiRequest(`/collection/analysis/${row.id}/apply`, { method: 'POST', body: { base_metadata_version: metadata[row.id], apply: [action==='apply'?'summary':action],confirmed_categories:chosenCategory[row.id]?[chosenCategory[row.id]]:[],confirmed_tags:chosenTags[row.id]??[] } })
      } else await apiRequest(`/collection/analysis/${row.id}/retry`, { method: 'POST' })
      notify('success', action === 'retry' ? '分析重试已受理' : '摘要建议已采用'); setVersion(v => v + 1)
    } catch (error) { notify('error', error instanceof Error ? error.message : '操作失败') }
  }
  async function retain(event: React.FormEvent) {
    event.preventDefault()
    try { await apiRequest(`/collection/results/${resultId}/retain`, { method: 'POST', body: { result_id: resultId, reason } }); notify('success', '已保留为待筛选素材'); setVersion(v => v + 1) }
    catch (error) { notify('error', error instanceof Error ? error.message : '保留失败') }
  }
  return <section aria-label="素材分析"><h2>素材分析</h2>{loading ? <p role="status">正在加载分析记录</p> : error ? <p role="alert">{error}</p> : rows.length === 0 ? <p>暂无分析记录</p> : rows.map(row => <article key={row.id} className="analysis-row">
    <h3>{row.purpose==='compare'?'新进展比较':'素材分析'} · 尝试 {row.attempt} · {row.status}{row.stale ? ' · 已过期' : ''}</h3><p>提示词：{row.prompt_version} · 模型配置版本：{row.model_config_version ?? "未知"} · 正文：{row.input_hash?.slice(0,12) ?? "旧记录"}</p><p>{row.suggestions?.summary ?? row.error ?? '等待分析'}</p>
    {row.suggestions && <><p>相关性：{row.suggestions.relevance} · {row.suggestions.relevance_reason}</p>{row.suggestions.facts?.map((fact, i) => <blockquote key={i}><p>{fact.statement}</p><q>{fact.quote}</q></blockquote>)}<p>标签建议：{row.suggestions.tag_suggestions?.join('、')}</p></>}
    {row.status === 'failed' && !row.stale && <button type="button" onClick={() => void act(row, 'retry')}>重试分析</button>}
    {row.status === 'succeeded' && !row.stale && row.material_id && <>
      <p>元数据版本：{metadata[row.id]}</p><button type="button" onClick={() => void act(row, 'apply')}>采用摘要</button>
      <label>确认分类<select value={chosenCategory[row.id]??''} onChange={e=>setChosenCategory(v=>({...v,[row.id]:e.target.value}))}><option value="">选择已有分类</option>{categories.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <button type="button" disabled={!chosenCategory[row.id]} onClick={()=>void act(row,'category')}>采用分类</button>
      <fieldset><legend>确认标签</legend>{tags.map(tag=><label key={tag.id}><input type="checkbox" checked={(chosenTags[row.id]??[]).includes(tag.id)} onChange={e=>setChosenTags(v=>({...v,[row.id]:e.target.checked?[...(v[row.id]??[]),tag.id]:(v[row.id]??[]).filter(id=>id!==tag.id)}))}/>{tag.name}</label>)}</fieldset>
      <button type="button" disabled={!chosenTags[row.id]?.length} onClick={()=>void act(row,'tags')}>采用标签</button>
    </>}
  </article>)}{resultId && <form onSubmit={retain}><label>保留原因<input required value={reason} onChange={e => setReason(e.target.value)} /></label><button type="submit">保留为待筛选素材</button></form>}</section>
}
