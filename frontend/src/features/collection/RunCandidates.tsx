import { useEffect, useState } from 'react'
import { apiRequest } from '../../shared/api/client'
import { useFeedback } from '../../shared/components/feedback'
type Candidate = { id: string; url: string; title?: string; summary?: string; provider_rank?: number; status: string; error: string | null; attempts: { id: string; stage: string; status: string; attempt: number; error?: string }[]; snapshot?: { markdown?: string; extractor_version?: string; content_hash?: string } }
export function RunCandidates({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Candidate[]>([])
  const [error, setError] = useState('')
  const { notify } = useFeedback()
  useEffect(() => {
    const controller = new AbortController()
    async function refresh() { try { setRows(await apiRequest<Candidate[]>(`/collection/runs/${runId}/candidates`, { signal: controller.signal })); setError('') } catch (error) { if (!controller.signal.aborted) setError(String(error)) } }
    void refresh(); const timer = setInterval(() => void refresh(), 4000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [runId])
  async function retry() { try { await apiRequest(`/collection/runs/${runId}/retry`, { method: 'POST' }); notify('success', '失败阶段重试已受理') } catch (error) { notify('error', String(error)) } }
  return <section aria-label="候选与阶段"><h2>候选与阶段</h2><button type="button" onClick={() => void retry()}>恢复失败阶段</button>{error && <p role="alert">{error}</p>}{rows.length === 0 && !error && <p>暂无发现候选</p>}{rows.map(row => <details key={row.id}><summary>{row.url} · {row.status} {row.error}</summary>{row.summary && <p>搜索发现摘要：{row.summary}</p>}{row.provider_rank && <p>搜索排名：{row.provider_rank}</p>}<ol>{row.attempts.map(a => <li key={a.id}>{a.stage} · {a.status} · 尝试 {a.attempt} {a.error}</li>)}</ol>{row.snapshot && <><p>提取器：{row.snapshot.extractor_version} · 正文版本：{row.snapshot.content_hash?.slice(0, 12)}</p><pre className="article-body">{row.snapshot.markdown}</pre></>}</details>)}</section>
}
