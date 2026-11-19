import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { navigate, setNavigationGuard } from '../../app/router'
import { ApiError } from '../../shared/api/client'
import { articleApi, articleStatuses, defaultLayout, reviewLabels, type AiAction, type Article, type ArticleContent, type Layout, type Page, type Review, type Revision } from '../../shared/api/articles'
import type { GenerationModel } from '../../shared/api/creation'
import { FileUploadDemo } from '../dashboard/FileUploadDemo'
import { MaterialSearchPage } from '../materials/MaterialSearchPage'
import './content.css'
import { PublishPanel } from './PublishPanel'
import { DraftDeliveryPanel } from './DraftDeliveryPanel'
import { QualityPanel } from '../assistance/AssistancePanels'

const empty: ArticleContent = { title: '', author: '', summary: '', keywords: [], body_markdown: '', cover_object_id: null, layout_config: defaultLayout, materials: [] }
const aiLabels: Record<AiAction, string> = { polish: '润色', continue: '续写', expand: '扩写', shorten: '缩写', rewrite: '改写', title: '标题优化', summary: '摘要建议' }
function contentOf(value: ArticleContent): ArticleContent { return { title: value.title, author: value.author, summary: value.summary, keywords: value.keywords, body_markdown: value.body_markdown, cover_object_id: value.cover_object_id, layout_config: { ...defaultLayout, ...value.layout_config }, materials: value.materials.map(({ material_id, material_revision_id }) => ({ material_id, material_revision_id })) } }

export function ArticleEditor({ id }: { id?: string }) {
  const { hasPermission } = useAuth()
  const write = hasPermission('article:write')
  const canReview = hasPermission('article:review')
  const [article, setArticle] = useState<Article | null>(null)
  const onPublished = useCallback(() => setArticle(value => value && value.status !== 'published' ? { ...value, status: 'published' } : value), [])
  const [content, setContent] = useState<ArticleContent>(empty)
  const [baseline, setBaseline] = useState(JSON.stringify(empty))
  const [base, setBase] = useState('')
  const [history, setHistory] = useState<Page<Revision> | null>(null)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyRevision, setHistoryRevision] = useState<Revision | null>(null)
  const [reviews, setReviews] = useState<Page<Review> | null>(null)
  const [reviewPage, setReviewPage] = useState(1)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(Boolean(id))
  const [conflict, setConflict] = useState<Article | null>(null)
  const [html, setHtml] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [models, setModels] = useState<GenerationModel[]>([])
  const [model, setModel] = useState('')
  const [aiAction, setAiAction] = useState<AiAction>('polish')
  const [suggestion, setSuggestion] = useState<{ text: string; action: AiAction; source: string } | null>(null)
  const [checks, setChecks] = useState<Record<string, string>>({})
  const [comment, setComment] = useState('')
  const [reviewAction, setReviewAction] = useState('approve')
  const [keywordsText, setKeywordsText] = useState('')
  const [chooseMaterial, setChooseMaterial] = useState(false)
  const [imageUrl, setImageUrl] = useState('')
  const alive = useRef(true)
  const dirty = JSON.stringify(content) !== baseline
  const editable = write && !historyRevision && article?.status !== 'published'
  const viewedRevision = historyRevision?.id || base
  const displayContent = historyRevision || content
  const currentContent = useRef(content)
  useEffect(() => { currentContent.current = content }, [content])
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  function applyCurrent(value: Article) {
    setArticle(value); setBase(value.revision_id); const next = contentOf(value)
    setContent(next); setBaseline(JSON.stringify(next)); setHistoryRevision(null); setSuggestion(null); setConflict(null)
    setKeywordsText(next.keywords.join(','))
    setChecks({}); setComment(''); setReviewPage(1)
  }
  async function load() {
    if (!id) { setLoading(false); return }
    setLoading(true); setError('')
    try { const value = await articleApi.detail(id); if (alive.current) applyCurrent(value) }
    catch (cause) { if (alive.current) setError(cause instanceof Error ? cause.message : '加载失败') }
    finally { if (alive.current) setLoading(false) }
  }
  useEffect(() => { void load() /* component is keyed by article id */ }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!write) return
    let active = true
    void articleApi.models().then(value => { if (active) { setModels(value); setModel(value[0]?.id || '') } }).catch(() => { if (active) setModels([]) })
    return () => { active = false }
  }, [write])
  useEffect(() => {
    setNavigationGuard(dirty ? () => window.confirm('文章尚未保存，确定离开并丢弃修改吗？') : null)
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', beforeUnload)
    return () => { setNavigationGuard(null); window.removeEventListener('beforeunload', beforeUnload) }
  }, [dirty])
  useEffect(() => {
    let active = true
    setHtml(''); setPreviewError('')
    const timer = window.setTimeout(() => {
      void articleApi.preview(displayContent.body_markdown, { ...defaultLayout, ...displayContent.layout_config }).then(value => { if (active) setHtml(value.html) }).catch(cause => { if (active) setPreviewError(cause instanceof Error ? cause.message : '预览失败') })
    }, 250)
    return () => { active = false; window.clearTimeout(timer) }
  }, [displayContent.body_markdown, displayContent.layout_config])
  useEffect(() => {
    if (!id || !base) return
    let active = true
    void articleApi.revisions(id, historyPage).then(value => { if (active) setHistory(value) }).catch(cause => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [id, base, historyPage])
  useEffect(() => {
    if (!viewedRevision) return
    let active = true
    setReviews(null)
    void articleApi.reviews(viewedRevision, reviewPage).then(value => { if (active) setReviews(value) }).catch(cause => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [viewedRevision, reviewPage, article?.status])
  function patch(values: Partial<ArticleContent>) { setContent(old => ({ ...old, ...values })); setMessage('') }
  function layout(values: Partial<Layout>) { patch({ layout_config: { ...content.layout_config, ...values } }) }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await work() }
    catch (cause) {
      setError(cause instanceof Error ? cause.message : '操作失败')
      if (cause instanceof ApiError && cause.status === 409 && id) {
        try { setConflict(await articleApi.detail(id)) } catch { /* preserve original failure and local content */ }
      }
    } finally { if (alive.current) setBusy(false) }
  }
  async function save() {
    await act(async () => {
      const snapshot = content
      const result = await articleApi.save(snapshot, id, base)
      if (!alive.current) return
      setBaseline(JSON.stringify(snapshot)); setBase(result.current_revision_id); setSuggestion(null)
      if (!id) { setNavigationGuard(null); navigate(`/content/articles/${result.article_id}`) }
      else { const value = await articleApi.detail(id); setArticle(value); setConflict(null) }
      setMessage('已保存新版本，需要提交人工审核。')
    })
  }
  function addImage(url: string) {
    if (!/^https?:\/\/[^\s()]+$/i.test(url) && !/^\/api\/v1\/files\/[0-9a-f-]{36}\/image$/i.test(url)) { setError('请输入有效的 HTTP/HTTPS 图片地址'); return }
    patch({ body_markdown: `${content.body_markdown}\n\n![图片](${url})` }); setImageUrl('')
  }
  if (loading) return <p role="status">正在加载文章…</p>
  if (id && !article) return <div role="alert">{error}<button onClick={() => void load()}>重试</button></div>
  return <section className="article-editor">
    <header className="editor-toolbar"><div><h1>{id ? '文章编辑与审核' : '新建文章'}</h1><p>{article ? `${articleStatuses[article.status]} · 当前 v${article.version}` : '人工草稿'}{dirty && ' · 有未保存修改'}{historyRevision && ` · 正在查看历史 v${historyRevision.version}`}</p></div><div>
      <button onClick={() => { const back = new URLSearchParams(window.location.hash.split('?')[1] || '').get('list'); window.location.hash = back?.startsWith('#/content?') ? back : '#/content' }}>返回列表</button>
      {editable && <button disabled={busy} onClick={() => void save()}>保存新版本</button>}
      {id && editable && <button disabled={busy || dirty || !['draft', 'returned', 'rejected'].includes(article?.status || '')} onClick={() => void act(async () => { await articleApi.submit(id, base); await load(); setMessage('已提交当前版本审核。') })}>提交审核</button>}
    </div></header>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {conflict && <aside role="alert"><p>服务器最新为 v{conflict.version}：{conflict.title}。本地修改已保留，可复制后手工合并。</p><details><summary>查看最新正文</summary><pre>{conflict.body_markdown}</pre></details><button onClick={() => { if (!dirty || window.confirm('读取服务器版本会丢弃本地修改，是否继续？')) applyCurrent(conflict) }}>读取最新版本</button></aside>}
    {historyRevision && <button onClick={() => { setHistoryRevision(null); setReviewPage(1) }}>返回当前版本</button>}
    <div className="editor-columns"><div className="editor-main"><fieldset disabled={!editable || busy}>
      <label>文章标题<input value={displayContent.title} maxLength={512} onChange={e => patch({ title: e.target.value })} /></label>
      <label>作者<input value={displayContent.author} onChange={e => patch({ author: e.target.value })} /></label>
      <label>摘要<textarea value={displayContent.summary} onChange={e => patch({ summary: e.target.value })} /></label>
      <label>关键词（逗号分隔）<input value={historyRevision ? displayContent.keywords.join(',') : keywordsText} onChange={e => { setKeywordsText(e.target.value); patch({ keywords: e.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean) }) }} /></label>
      <label>Markdown 正文<textarea className="markdown-editor" rows={20} value={displayContent.body_markdown} onChange={e => patch({ body_markdown: e.target.value })} /></label>
    </fieldset>
    {editable && <details><summary>封面与正文图片</summary><label>图片地址<input value={imageUrl} onChange={e => setImageUrl(e.target.value)} /></label><button disabled={busy} onClick={() => addImage(imageUrl)}>插入图片</button><p>修改正文中的图片地址可替换图片。也可上传图片后设为封面或插入正文。</p>
      <FileUploadDemo onRegistered={stored => { if (!stored.content_type.startsWith('image/') || stored.content_type === 'image/svg+xml') { setError('请选择 PNG/JPEG/WebP/GIF 图片'); return } patch({ cover_object_id: stored.id }); setImageUrl(`/api/v1/files/${stored.id}/image`) }} />
      <button disabled={!content.cover_object_id || busy} onClick={() => patch({ cover_object_id: null })}>移除封面</button>
    </details>}
    {displayContent.cover_object_id && <img className="article-cover" src={`/api/v1/files/${displayContent.cover_object_id}/image`} alt="文章封面" />}
    <h2>引用素材及当时正文</h2>
    {displayContent.materials.length === 0 && <p>暂无引用</p>}
    {displayContent.materials.map((ref, index) => {
      const source = article?.materials.find(item => item.material_revision_id === ref.material_revision_id)
      return <article key={ref.material_id}><a href={`#/materials?material_id=${ref.material_id}`}>{source?.title || ref.material_id}</a><p>修订：{ref.material_revision_id}</p>{source?.source_url && /^https?:\/\//i.test(source.source_url) && <a href={source.source_url} target="_blank" rel="noopener noreferrer">原始来源</a>}{source && <details><summary>当时引用正文</summary><pre>{source.content_markdown}</pre></details>}{editable && <button onClick={() => patch({ materials: content.materials.filter((_, i) => i !== index) })}>移除引用</button>}</article>
    })}
    {editable && hasPermission('material:search') && <div><button onClick={() => setChooseMaterial(value => !value)}>{chooseMaterial ? '收起素材检索' : '从素材库添加引用'}</button>{chooseMaterial && <MaterialSearchPage onPick={item => { if (content.materials.some(ref => ref.material_id === item.material_id)) { setError('同一素材不能重复引用'); return } patch({ materials: [...content.materials, { material_id: item.material_id, material_revision_id: item.matched_revision_id }] }); setMessage(`已添加引用：${item.title}，保存后生效。`) }} />}</div>}
    </div><aside className="editor-side">
      <h2>排版与手机预览</h2><fieldset disabled={!editable || busy}>
        <label>模板<select value={displayContent.layout_config.template} onChange={e => layout({ template: e.target.value as Layout['template'] })}><option value="classic">经典</option><option value="news">新闻</option><option value="minimal">简洁</option></select></label>
        <label>字体<select value={displayContent.layout_config.font_family} onChange={e => layout({ font_family: e.target.value as Layout['font_family'] })}><option value="sans-serif">黑体</option><option value="serif">宋体</option></select></label>
        <label>字号<input type="number" min={12} max={24} value={displayContent.layout_config.font_size} onChange={e => layout({ font_size: Number(e.target.value) })} /></label>
        <label>行距<input type="number" min={1.2} max={2.5} step={0.1} value={displayContent.layout_config.line_height} onChange={e => layout({ line_height: Number(e.target.value) })} /></label>
        <label>段落间距<input type="number" min={0} max={40} value={displayContent.layout_config.paragraph_spacing} onChange={e => layout({ paragraph_spacing: Number(e.target.value) })} /></label>
        <label>图片样式<select value={displayContent.layout_config.image_style} onChange={e => layout({ image_style: e.target.value as Layout['image_style'] })}><option value="rounded">圆角</option><option value="square">直角</option></select></label>
      </fieldset>
      {previewError ? <p role="alert">{previewError}</p> : <iframe className="phone-preview" title="手机预览" sandbox="allow-same-origin" srcDoc={html} />}
      {id && editable && <><h2>AI 编辑建议</h2><p>建议基于已保存版本。采用后仍需保存并重新审核。</p><label>生成模型<select value={model} onChange={e => setModel(e.target.value)}><option value="">请选择模型</option>{models.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{!models.length && <p>暂无可用生成模型，请联系管理员配置。</p>}<label>编辑动作<select value={aiAction} onChange={e => setAiAction(e.target.value as AiAction)}>{Object.entries(aiLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button disabled={busy || dirty || !model} onClick={() => void act(async () => { const snapshot = JSON.stringify(content); const result = await articleApi.suggest(id, base, aiAction, model); if (JSON.stringify(currentContent.current) !== snapshot) throw new Error('本地编辑已变化，请重新生成建议'); setSuggestion({ text: result.suggestion, action: aiAction, source: snapshot }) })}>生成建议</button>
      {suggestion && <div><pre>{suggestion.text}</pre><button disabled={busy || JSON.stringify(content) !== suggestion.source} onClick={() => { if (suggestion.action === 'title') patch({ title: suggestion.text }); else if (suggestion.action === 'summary') patch({ summary: suggestion.text }); else patch({ body_markdown: suggestion.action === 'continue' ? `${content.body_markdown}\n\n${suggestion.text}` : suggestion.text }); setSuggestion(null) }}>采用建议到编辑区</button><button onClick={() => setSuggestion(null)}>不采用</button></div>}
      </>}
    </aside></div>
    {id && base && !historyRevision && !dirty && hasPermission('material:read') && <QualityPanel key={`${id}:${base}`} articleId={id} revisionId={base} />}
    {id && <><h2>版本历史</h2>{history?.items.map(row => <button key={row.id} disabled={busy} onClick={() => { if (dirty && !window.confirm('有未保存修改，仍查看历史版本吗？')) return; setHistoryRevision({ ...row, layout_config: { ...defaultLayout, ...row.layout_config } }); setReviewPage(1) }}>查看 v{row.version}</button>)}<button disabled={historyPage <= 1} onClick={() => setHistoryPage(value => value - 1)}>上一页版本</button><button disabled={!history || historyPage * 20 >= history.total} onClick={() => setHistoryPage(value => value + 1)}>下一页版本</button>
    <h2>审核历史（{historyRevision ? `v${historyRevision.version}` : `v${article?.version}`}）</h2>{reviews?.items.length === 0 && <p>该修订暂无审核记录</p>}{reviews?.items.map(row => <article key={row.id}><p>{({ approve: '审核通过', return: '退回修改', reject: '审核驳回' } as Record<string, string>)[row.action]} · {new Date(row.created_at).toLocaleString()} · 审核人 {row.reviewer_id}</p><p>{row.comment}</p><details><summary>检查项</summary>{Object.entries(row.checklist).map(([key, value]) => <p key={key}>{reviewLabels[key]}：{({ pass: '通过', fail: '未通过', not_applicable: '不适用' } as Record<string, string>)[value || ''] || '未检查'}</p>)}</details></article>)}<button disabled={reviewPage <= 1} onClick={() => setReviewPage(value => value - 1)}>上一页审核</button><button disabled={!reviews || reviewPage * 20 >= reviews.total} onClick={() => setReviewPage(value => value + 1)}>下一页审核</button>
    {canReview && !historyRevision && article?.status === 'pending_review' && <form className="review-form" onSubmit={e => { e.preventDefault(); void act(async () => { await articleApi.review(base, { action: reviewAction, checklist: checks, comment }); await load(); setMessage('审核结论已保存到该版本。') }) }}><h2>审核当前 v{article.version}</h2><fieldset disabled={busy || dirty}>{Object.entries(reviewLabels).map(([key, label]) => <label key={key}>{label}<select value={checks[key] || ''} onChange={e => setChecks(old => ({ ...old, [key]: e.target.value }))}><option value="">未检查</option><option value="pass">通过</option><option value="fail">未通过</option>{key === 'image_copyright' && <option value="not_applicable">不适用</option>}</select></label>)}<label>审核结论<select value={reviewAction} onChange={e => setReviewAction(e.target.value)}><option value="approve">通过</option><option value="return">退回修改</option><option value="reject">驳回</option></select></label><label>审核意见<textarea required={reviewAction !== 'approve'} value={comment} onChange={e => setComment(e.target.value)} /></label><button disabled={reviewAction === 'approve' ? Object.keys(reviewLabels).some(key => checks[key] !== 'pass' && !(key === 'image_copyright' && checks[key] === 'not_applicable')) : !comment.trim()}>提交审核结论</button></fieldset></form>}
    </>}
    {id && article && !historyRevision && <><DraftDeliveryPanel articleId={id} revisionId={base} articleStatus={article.status} dirty={dirty} onPublished={onPublished} /><details><summary>有接口发布权限的账号：自动发布管理</summary><PublishPanel articleId={id} revisionId={base} articleStatus={article.status} dirty={dirty} onPublished={onPublished} /></details></>}
  </section>
}
