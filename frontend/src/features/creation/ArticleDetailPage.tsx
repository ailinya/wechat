import { useEffect, useState } from 'react'
import { apiRequest } from '../../shared/api/client'

interface Article {
  id: string; status: string; title: string; summary: string; body_markdown: string; keywords: string[]
  materials: { material_id: string; material_revision_id: string; title: string; content_markdown: string; source_url: string | null }[]
}

function safeSource(value: string | null): string | null {
  if (!value) return null
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null } catch { return null }
}

export function ArticleDetailPage({ id }: { id: string }) {
  const [article, setArticle] = useState<Article | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setArticle(null); setError('')
    void apiRequest<Article>(`/articles/${encodeURIComponent(id)}`).then(value => { if (active) setArticle(value) }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '文章加载失败') })
    return () => { active = false }
  }, [id])
  if (error) return <p role="alert">{error}</p>
  if (!article) return <p role="status">正在加载文章…</p>
  return <section className="list-page"><h1>{article.title}</h1><p>状态：{article.status === 'pending_review' ? '待审核' : article.status}</p><p>{article.summary}</p><pre>{article.body_markdown}</pre><p>关键词：{article.keywords.join('、')}</p><h2>引用素材及当时正文</h2>{article.materials.map(material => <article key={material.material_revision_id}><h3><a href={`#/materials?material_id=${material.material_id}`}>{material.title}</a></h3><p>素材修订：{material.material_revision_id}</p>{safeSource(material.source_url) && <a href={safeSource(material.source_url) || undefined} target="_blank" rel="noopener noreferrer">查看原始来源</a>}<pre>{material.content_markdown}</pre></article>)}</section>
}
