import { useEffect, useState } from 'react'
import { apiRequest } from '../../shared/api/client'
import { useAuth } from '../../app/AuthContext'
import { useFeedback } from '../../shared/components/feedback'
import type { ModelConfigOut, SearchConfigOut } from '../../shared/api/types'

export function CollectionSettings() {
  const [models, setModels] = useState<ModelConfigOut[]>([])
  const [searches, setSearches] = useState<SearchConfigOut[]>([])
  const [version, setVersion] = useState(0)
  const [error, setError] = useState('')
  const { hasPermission } = useAuth()
  const { notify } = useFeedback()
  const writable = hasPermission('settings:write')
  useEffect(() => {
    const controller = new AbortController()
    void Promise.all([
      apiRequest<{ items: ModelConfigOut[] }>('/model-configs?page_size=100', { signal: controller.signal }),
      apiRequest<{ items: SearchConfigOut[] }>('/search-configs?page_size=100', { signal: controller.signal }),
    ]).then(([m, s]) => { setModels(m.items); setSearches(s.items); setError('') }).catch(error => { if (!controller.signal.aborted) setError(String(error)) })
    return () => controller.abort()
  }, [version])
  async function save(event: React.FormEvent<HTMLFormElement>, kind: 'search' | 'model') {
    event.preventDefault(); const form = new FormData(event.currentTarget); const value = (key: string) => String(form.get(key) ?? '')
    const body = kind === 'search' ? { name: value('name'), provider: 'tavily', credential_ref: value('credential_ref') || null } : {
      name: value('name'), provider: 'openai-compatible', purpose: 'analysis', endpoint: value('endpoint'), model_name: value('model_name'),
      credential_ref: value('credential_ref') || null, max_input_tokens: Number(value('input')), max_output_tokens: Number(value('output')), timeout_seconds: Number(value('timeout')),
    }
    try { await apiRequest(kind === 'search' ? '/search-configs' : '/model-configs', { method: 'POST', body }); notify('success', '配置已保存'); setVersion(v => v + 1) }
    catch (error) { notify('error', String(error)) }
  }
  async function test(kind: string, id: string) {
    try { const result = await apiRequest<{ reachable: boolean; latency_ms: number; error?: string }>(`/${kind}-configs/${id}/test`, { method: 'POST' }); notify(result.reachable ? 'success' : 'error', result.reachable ? `连接正常 · ${result.latency_ms}ms` : result.error ?? '连接失败') }
    catch (error) { notify('error', String(error)) }
  }
  async function toggle(kind:string,id:string,enabled:boolean) {
    try {await apiRequest(`/${kind}-configs/${id}`,{method:'PATCH',body:{enabled:!enabled}});setVersion(v=>v+1);notify('success',enabled?'配置已停用':'配置已启用')}
    catch(error){notify('error',String(error))}
  }
  return <section className="list-page"><h1>系统设置</h1>{error && <p role="alert">{error}</p>}<h2>搜索配置</h2>{writable && <form className="collection-form" onSubmit={e => void save(e, 'search')}><label>配置名称<input name="name" required /></label><label>凭据引用<input name="credential_ref" pattern="[A-Z][A-Z0-9_]*" placeholder="TAVILY_API_KEY" /></label><button type="submit">新增搜索配置</button></form>}
    <table><thead><tr><th>名称</th><th>提供方</th><th>启用</th><th>凭据</th><th>操作</th></tr></thead><tbody>{searches.map(row => <tr key={row.id}><td>{row.name}</td><td>{row.provider}</td><td>{row.enabled ? '是' : '否'}</td><td>{row.credential_configured ? '已配置' : '未配置'}</td><td>{writable && <><button type="button" onClick={() => void test('search', row.id)}>测试连接</button><button type="button" onClick={() => void toggle('search',row.id,row.enabled)}>{row.enabled?'停用':'启用'}</button></>}</td></tr>)}</tbody></table>
    <h2>分析模型</h2>{writable && <form className="collection-form" onSubmit={e => void save(e, 'model')}><label>配置名称<input name="name" required /></label><label>接口地址<input type="url" name="endpoint" required /></label><label>模型名称<input name="model_name" required /></label><label>凭据引用<input name="credential_ref" /></label><label>输入上限<input type="number" name="input" min="1" defaultValue="8000" required /></label><label>输出上限<input type="number" name="output" min="1" defaultValue="2000" required /></label><label>超时秒数<input type="number" name="timeout" min="1" max="600" defaultValue="60" required /></label><button type="submit">新增分析模型</button></form>}
    <table><thead><tr><th>名称</th><th>模型</th><th>启用</th><th>凭据</th><th>操作</th></tr></thead><tbody>{models.map(row => <tr key={row.id}><td>{row.name}</td><td>{row.model_name}</td><td>{row.enabled ? '是' : '否'}</td><td>{row.credential_configured ? '已配置' : '未配置'}</td><td>{writable && <><button type="button" onClick={() => void test('model', row.id)}>测试连接</button><button type="button" onClick={() => void toggle('model',row.id,row.enabled)}>{row.enabled?'停用':'启用'}</button></>}</td></tr>)}</tbody></table></section>
}
