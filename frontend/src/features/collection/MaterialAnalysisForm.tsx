import { useEffect,useState } from 'react'
import { apiRequest } from '../../shared/api/client'
import { useFeedback } from '../../shared/components/feedback'

export function MaterialAnalysisForm({materialId}:{materialId:string}) {
  const [models,setModels]=useState<{id:string;name:string}[]>([])
  const [model,setModel]=useState('')
  const [busy,setBusy]=useState(false)
  const {notify}=useFeedback()
  useEffect(()=>{const controller=new AbortController();void apiRequest<{models:{id:string;name:string}[]}>('/collection/config-options',{signal:controller.signal}).then(data=>setModels(data.models??[])).catch(()=>{});return ()=>controller.abort()},[])
  async function submit(event:React.FormEvent){
    event.preventDefault();setBusy(true)
    try{await apiRequest(`/materials/${materialId}/analysis`,{method:'POST',body:{model_config_id:model}});notify('success','素材修订分析已受理')}
    catch(error){notify('error',String(error))}finally{setBusy(false)}
  }
  return <form className="list-filters" onSubmit={submit}><label>独立分析模型<select required value={model} onChange={e=>setModel(e.target.value)}><option value="">选择分析模型</option>{models.map(v=><option key={v.id} value={v.id}>{v.name}</option>)}</select></label><button type="submit" disabled={busy||!model}>分析当前修订</button></form>
}
