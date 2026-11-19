import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ArticleEditor } from './ArticleEditor'
import { articleApi, defaultLayout, type Article } from '../../shared/api/articles'
import { ApiError } from '../../shared/api/client'

const permissions = vi.hoisted(() => ({ write: true, review: true }))
vi.mock('../../app/AuthContext', () => ({ useAuth: () => ({ hasPermission: (code: string) => code === 'article:write' ? permissions.write : code === 'article:review' ? permissions.review : true }) }))
vi.mock('../dashboard/FileUploadDemo', () => ({ FileUploadDemo: () => <p>上传图片</p> }))
vi.mock('./PublishPanel', () => ({ PublishPanel: () => null }))
vi.mock('../../shared/api/articles', async importOriginal => {
  const original = await importOriginal<typeof import('../../shared/api/articles')>()
  return { ...original, articleApi: { detail: vi.fn(), revisions: vi.fn(), revision: vi.fn(), reviews: vi.fn(), preview: vi.fn(), save: vi.fn(), submit: vi.fn(), review: vi.fn(), suggest: vi.fn(), models: vi.fn() } }
})
const api = vi.mocked(articleApi)
const article: Article = { id: 'a1', revision_id: 'r1', version: 1, status: 'draft', title: '原始标题', author: '作者', summary: '摘要', keywords: ['关键词'], body_markdown: '原始正文', cover_object_id: null, layout_config: defaultLayout, materials: [], origin_type: 'manual', created_at: '2026-11-19T00:00:00Z', updated_at: '2026-11-19T00:00:00Z' }
beforeEach(() => {
  vi.clearAllMocks(); permissions.write = true; permissions.review = true
  api.detail.mockResolvedValue(article)
  api.revisions.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  api.reviews.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  api.preview.mockResolvedValue({ html: '<p>安全预览</p>' })
  api.models.mockResolvedValue([{ id: 'm1', name: '生成模型', model_name: 'fixture' }])
})

it('保存冲突保留本地正文，展示最新版本以便合并', async () => {
  const user = userEvent.setup()
  render(<ArticleEditor id="a1" />)
  const body = await screen.findByLabelText('Markdown 正文')
  await user.clear(body); await user.type(body, '本地修改正文')
  api.save.mockRejectedValue(new ApiError(409, 'revision_conflict', '文章已被修改'))
  api.detail.mockResolvedValue({ ...article, revision_id: 'r2', version: 2, body_markdown: '他人修改正文' })
  await user.click(screen.getByRole('button', { name: '保存新版本' }))
  expect(await screen.findByText(/服务器最新为 v2/)).toBeInTheDocument()
  expect(body).toHaveValue('本地修改正文')
  expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ body_markdown: '本地修改正文' }), 'a1', 'r1')
})

it('AI 建议选择采用后仍需显式保存，排版配置一起提交', async () => {
  const user = userEvent.setup()
  api.suggest.mockResolvedValue({ suggestion: '建议正文', base_revision_id: 'r1' })
  api.save.mockResolvedValue({ article_id: 'a1', current_revision_id: 'r2', revision: { ...article, id: 'r2', article_id: 'a1', version: 2 }, status: 'draft' })
  render(<ArticleEditor id="a1" />)
  await screen.findByLabelText('Markdown 正文')
  await user.click(screen.getByRole('button', { name: '生成建议' }))
  expect(await screen.findByText('建议正文')).toBeInTheDocument()
  expect(api.save).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '采用建议到编辑区' }))
  expect(screen.getByLabelText('Markdown 正文')).toHaveValue('建议正文')
  expect(api.save).not.toHaveBeenCalled()
  await user.selectOptions(screen.getByLabelText('模板'), 'news')
  await user.click(screen.getByRole('button', { name: '保存新版本' }))
  await waitFor(() => expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ body_markdown: '建议正文', layout_config: expect.objectContaining({ template: 'news' }) }), 'a1', 'r1'))
})

it('审核明确版本，退回必须有意见，阅读者无法编辑', async () => {
  const user = userEvent.setup()
  permissions.write = false
  api.detail.mockResolvedValue({ ...article, status: 'pending_review' })
  api.review.mockResolvedValue({ id: 'review1', article_revision_id: 'r1', action: 'return', checklist: {}, comment: '核对事实', reviewer_id: 'u1', created_at: article.created_at })
  render(<ArticleEditor id="a1" />)
  expect(await screen.findByRole('heading', { name: '审核当前 v1' })).toBeInTheDocument()
  expect(screen.getByLabelText('Markdown 正文')).toBeDisabled()
  expect(screen.queryByRole('button', { name: '保存新版本' })).not.toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText('审核结论'), 'return')
  expect(screen.getByRole('button', { name: '提交审核结论' })).toBeDisabled()
  await user.type(screen.getByLabelText('审核意见'), '核对事实')
  await user.click(screen.getByRole('button', { name: '提交审核结论' }))
  await waitFor(() => expect(api.review).toHaveBeenCalledWith('r1', expect.objectContaining({ action: 'return', comment: '核对事实' })))
})
