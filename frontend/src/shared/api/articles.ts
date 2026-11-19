import { apiRequest } from './client'

export interface Layout { template: 'classic' | 'news' | 'minimal'; font_family: 'sans-serif' | 'serif'; font_size: number; line_height: number; paragraph_spacing: number; image_style: 'square' | 'rounded' }
export const defaultLayout: Layout = { template: 'classic', font_family: 'sans-serif', font_size: 16, line_height: 1.8, paragraph_spacing: 16, image_style: 'rounded' }
export interface Reference { material_id: string; material_revision_id: string }
export interface ArticleContent { title: string; author: string; summary: string; keywords: string[]; body_markdown: string; cover_object_id: string | null; layout_config: Layout; materials: Reference[] }
export interface Article extends ArticleContent { id: string; revision_id: string; version: number; status: string; origin_type: string; created_at: string; updated_at: string; materials: (Reference & { title: string; content_markdown: string; source_url: string | null })[] }
export interface Revision extends ArticleContent { id: string; article_id: string; version: number; created_at: string }
export interface ArticleSummary { id: string; current_revision_id: string; title: string; author: string; status: string; version: number; origin_type: string; created_at: string; updated_at: string; publish_summary?: Record<string, number>; draft_summary?: Record<string, number> }
export interface Review { id: string; article_revision_id: string; action: string; checklist: Record<string, string | null>; comment: string; reviewer_id: string; created_at: string }
export interface QueueItem { article_id: string; article_revision_id: string; title: string; version: number; submitted_at: string }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export type AiAction = 'polish' | 'continue' | 'expand' | 'shorten' | 'rewrite' | 'title' | 'summary'
export const articleApi = {
  models: () => apiRequest<{ id: string; name: string; model_name: string }[]>('/articles/models'),
  list: (query: string) => apiRequest<Page<ArticleSummary>>(`/articles?${query}`),
  detail: (id: string) => apiRequest<Article>(`/articles/${id}`),
  revisions: (id: string, page = 1) => apiRequest<Page<Revision>>(`/articles/${id}/revisions?page=${page}&page_size=20`),
  revision: (id: string, rid: string) => apiRequest<Revision>(`/articles/${id}/revisions/${rid}`),
  save: (content: ArticleContent, id?: string, base?: string) => apiRequest<{ article_id: string; current_revision_id: string; revision: Revision; status: string }>(id ? `/articles/${id}/revisions` : '/articles', { method: 'POST', body: id ? { ...content, base_revision_id: base } : content }),
  submit: (id: string, base: string) => apiRequest(`/articles/${id}/submit-review`, { method: 'POST', body: { base_revision_id: base } }),
  queue: (page = 1) => apiRequest<Page<QueueItem>>(`/reviews/queue?page=${page}&page_size=20`),
  reviews: (rid: string, page = 1) => apiRequest<Page<Review>>(`/article-revisions/${rid}/reviews?page=${page}&page_size=20`),
  review: (rid: string, body: object) => apiRequest<Review>(`/article-revisions/${rid}/reviews`, { method: 'POST', body }),
  suggest: (id: string, base: string, action: AiAction, model: string) => apiRequest<{ suggestion: string; base_revision_id: string }>(`/articles/${id}/ai-actions`, { method: 'POST', body: { base_revision_id: base, action, model_config_id: model } }),
  preview: (body_markdown: string, layout_config: Layout) => apiRequest<{ html: string }>('/articles/preview', { method: 'POST', body: { body_markdown, layout_config } }),
}
export const articleStatuses: Record<string, string> = { draft: '草稿', pending_review: '待审核', approved: '审核通过／待发布', returned: '退回修改', rejected: '审核驳回', published: '已发布' }
export const reviewLabels: Record<string, string> = { title: '标题准确', content: '正文正确', facts: '事实与数据', citations: '引用来源', image_copyright: '图片版权与适用性', account_compliance: '公众号规范', layout: '排版' }
