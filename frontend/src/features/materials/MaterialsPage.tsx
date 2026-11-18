/** Material library page (task 3.10).
 *
 * URL-backed list with filters, a detail view showing the current Markdown
 * revision and origin, manual/link/upload creation, categories/tags,
 * favorites, archive/bulk actions, and a real empty state for the not-yet-
 * implemented "articles referencing this material" view (task 5.11).
 */

import { useEffect, useState } from 'react'
import { AnalysisPanel } from '../collection/AnalysisPanel'
import { MaterialAnalysisForm } from '../collection/MaterialAnalysisForm'

import { useHashRoute } from '../../app/router'
import { FileUploadDemo } from '../dashboard/FileUploadDemo'
import { materialsApi } from '../../shared/api/materials'
import { ApiError } from '../../shared/api/client'
import type { MaterialDetailOut, MaterialOut, StoredObjectOut } from '../../shared/api/types'
import { DataTable, type Column } from '../../shared/components/DataTable'
import { useFeedback } from '../../shared/components/feedback'
import { Pagination } from '../../shared/components/Pagination'
import { ListStates } from '../../shared/components/states'
import { useListView } from '../../shared/components/useListView'
import { useUrlQuery } from '../../shared/components/useUrlQuery'

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'pending_review', label: '待筛选' },
  { value: 'ready_to_use', label: '待使用' },
  { value: 'partially_used', label: '部分使用' },
  { value: 'used', label: '已使用' },
  { value: 'archived', label: '已归档' },
  { value: 'duplicate', label: '重复素材' },
]

const ORIGIN_LABELS: Record<string, string> = {
  collection: '采集', upload: '上传', link: '链接', manual: '手工',
  article: '文章', enterprise: '企业',
}

const columns: Column<MaterialOut>[] = [
  { key: 'title', header: '标题' },
  { key: 'origin', header: '来源', render: (row) => ORIGIN_LABELS[row.origin] ?? row.origin },
  { key: 'usage_status', header: '状态' },
  {
    key: 'tags',
    header: '标签',
    render: (row) => row.tags?.map((tag) => tag.name).join('、') || '—',
  },
]

function errorMessage(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : '操作失败，请稍后重试'
}

export function MaterialsPage() {
  const route = useHashRoute()
  const patchQuery = useUrlQuery(route.path, route.query)
  const notify = useFeedback().notify

  const page = Math.max(1, Number(route.query.get('page')) || 1)
  const pageSize = 10
  const usageStatus = route.query.get('usage_status') ?? ''
  const keyword = route.query.get('keyword') ?? ''
  const favoritesOnly = route.query.get('favorites') === '1'
  const selectedId = route.query.get('material_id') ?? route.path.match(/^\/materials\/([^/]+)$/)?.[1]

  const [keywordDraft, setKeywordDraft] = useState(keyword)
  const [createTitle, setCreateTitle] = useState('')
  const [createBody, setCreateBody] = useState('')
  const [linkUrl, setLinkUrl] = useState('')
  const [categoryName, setCategoryName] = useState('')
  const [tagName, setTagName] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [detail, setDetail] = useState<MaterialDetailOut | null>(null)
  useEffect(()=>{
    let active=true
    if(selectedId) void materialsApi.get(selectedId).then(data=>{if(active)setDetail(data)}).catch(()=>{})
    return ()=>{active=false}
  },[selectedId])

  const view = useListView<MaterialOut>('/materials', {
    page,
    pageSize,
    params: {
      usage_status: usageStatus || undefined,
      keyword: keyword || undefined,
      favorite_mine: favoritesOnly ? 'true' : undefined,
    },
  })

  async function openDetail(id: string) {
    try {
      const data = await materialsApi.get(id)
      setDetail(data)
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function createManual(event: React.FormEvent) {
    event.preventDefault()
    try {
      await materialsApi.create({ title: createTitle, content_markdown: createBody, tag_ids: [] })
      notify('success', '素材已创建')
      setCreateTitle('')
      setCreateBody('')
      view.retry()
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function createLink(event: React.FormEvent) {
    event.preventDefault()
    try {
      await materialsApi.createFromLink({ url: linkUrl })
      notify('success', '已从链接创建素材')
      setLinkUrl('')
      view.retry()
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function createFromUploaded(stored: StoredObjectOut) {
    try {
      await materialsApi.createFromUpload({ object_id: stored.id, title: stored.object_key })
      notify('success', '已从上传文件创建素材')
      view.retry()
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function toggleFavorite(material: MaterialOut) {
    try {
      if (material.id && detail?.favorited_by_me) {
        await materialsApi.unfavorite(material.id)
        notify('success', '已取消收藏')
      } else {
        await materialsApi.favorite(material.id)
        notify('success', '已收藏')
      }
      view.retry()
      if (detail) setDetail({ ...detail, favorited_by_me: !detail.favorited_by_me })
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function bulkAction(action: string) {
    if (!checked.size) {
      notify('error', '请先勾选素材')
      return
    }
    try {
      const outcome = await materialsApi.bulk({ material_ids: [...checked], action })
      notify('success', `批量操作完成：成功 ${outcome.counts.success ?? 0}，失败 ${outcome.counts.failed ?? 0}`)
      setChecked(new Set())
      view.retry()
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function addCategory(event: React.FormEvent) {
    event.preventDefault()
    try {
      await materialsApi.createCategory({ name: categoryName })
      notify('success', '分类已创建')
      setCategoryName('')
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  async function addTag(event: React.FormEvent) {
    event.preventDefault()
    try {
      await materialsApi.createTag({ name: tagName })
      notify('success', '标签已创建')
      setTagName('')
    } catch (cause) {
      notify('error', errorMessage(cause))
    }
  }

  return (
    <section className="list-page" aria-label="素材库">
      <h1>素材库</h1>

      <div className="material-tools">
        <form className="list-filters" onSubmit={(event) => {
          event.preventDefault()
          patchQuery({ keyword: keywordDraft || null, page: null })
        }}>
          <input type="search" aria-label="关键词筛选" placeholder="按标题搜索" value={keywordDraft}
            onChange={(event) => setKeywordDraft(event.target.value)} />
          <select aria-label="状态筛选" value={usageStatus}
            onChange={(event) => patchQuery({ usage_status: event.target.value || null, page: null })}>
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <button type="submit" className="primary-button">筛选</button>
          <button type="button" className="ghost-button"
            onClick={() => patchQuery({ favorites: favoritesOnly ? null : '1', page: null })}>
            {favoritesOnly ? '全部素材' : '我的收藏'}
          </button>
        </form>

        <form className="inline-form" onSubmit={createManual}>
          <input aria-label="素材标题" placeholder="手工素材标题" value={createTitle}
            onChange={(event) => setCreateTitle(event.target.value)} required />
          <input aria-label="素材正文" placeholder="中文正文（Markdown）" value={createBody}
            onChange={(event) => setCreateBody(event.target.value)} required />
          <button type="submit" className="primary-button">手工新建</button>
        </form>

        <form className="inline-form" onSubmit={createLink}>
          <input aria-label="素材链接" placeholder="https://example.com/article" value={linkUrl}
            onChange={(event) => setLinkUrl(event.target.value)} required />
          <button type="submit" className="primary-button">从链接创建</button>
        </form>

        <details className="upload-material">
          <summary>从文件创建素材（授权 → 直传 → 登记 → 解析）</summary>
          <p>文件失败时可在下方重试登记；页面不持有长期存储凭据。</p>
          <FileUploadDemo onRegistered={(stored) => void createFromUploaded(stored)} />
        </details>

        <div className="inline-form">
          <form onSubmit={addCategory}>
            <input aria-label="分类名称" placeholder="新分类名称" value={categoryName}
              onChange={(event) => setCategoryName(event.target.value)} required />
            <button type="submit" className="ghost-button">新增分类</button>
          </form>
          <form onSubmit={addTag}>
            <input aria-label="标签名称" placeholder="新标签名称" value={tagName}
              onChange={(event) => setTagName(event.target.value)} required />
            <button type="submit" className="ghost-button">新增标签</button>
          </form>
        </div>
      </div>

      <div className="list-filters">
        <button type="button" className="ghost-button" onClick={() => void bulkAction('archive')}>批量归档</button>
        <button type="button" className="ghost-button" onClick={() => void bulkAction('mark_ready')}>标记待使用</button>
        <span>已勾选 {checked.size} 项</span>
      </div>

      {view.status === 'ready' && view.data && (
        <>
          <DataTable
            columns={columns}
            rows={view.data.items}
            rowKey={(row) => row.id}
            caption="素材列表"
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
                <button type="button" className="ghost-button" onClick={() => {
                  patchQuery({ material_id: row.id })
                  void openDetail(row.id)
                }}>详情</button>
                <button type="button" className="ghost-button" onClick={() => void toggleFavorite(row)}>收藏</button>
              </>
            )}
          />
          <Pagination page={view.data.page} pageSize={view.data.page_size} total={view.data.total}
            onPageChange={(next) => patchQuery({ page: next === 1 ? null : next })}
            onPageSizeChange={() => undefined} />
        </>
      )}
      <ListStates status={view.status} error={view.error} emptyText="没有符合筛选条件的素材"
        onRetry={view.status === 'error' ? view.retry : undefined} />

      {selectedId && detail && (
        <section className="material-detail" aria-label="素材详情">
          <h2>{detail.title}</h2>
          <p>来源：{ORIGIN_LABELS[detail.origin] ?? detail.origin} · 状态：{detail.usage_status} · 当前修订 v{detail.current_revision.revision_no}</p>
          <pre className="material-body">{detail.current_revision.content_markdown}</pre>
          <AnalysisPanel materialId={detail.id} />
          <MaterialAnalysisForm materialId={detail.id} />
          <p>收藏数：{detail.favorite_count ?? 0}</p>
          <section className="material-references" aria-label="引用该素材的文章">
            <h3>引用文章</h3>
            <p>引用关系将在智能创作能力接入后显示。</p>
          </section>
          <button type="button" className="ghost-button" onClick={() => { setDetail(null); patchQuery({ material_id: null }) }}>关闭</button>
        </section>
      )}
    </section>
  )
}
