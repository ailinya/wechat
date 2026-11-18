/** Material library API calls (task 3.10). */

import { apiRequest } from './client'
import type {
  BulkActionOut,
  MaterialCategoryOut,
  MaterialCreateIn,
  MaterialDetailOut,
  MaterialLinkIn,
  MaterialOut,
  MaterialUpdateIn,
  MaterialUploadIn,
  PaginatedResponse_MaterialOut_,
  TagOut,
} from './types'

function pageQuery(page: number, pageSize: number, params: Record<string, string | undefined> = {}) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value)
  return query.toString()
}

export interface SearchItem {
  material_id: string
  title: string
  matched_revision_id: string
  snippet: string
  source: { type: string; title: string | null; url: string | null; attachment_id: string | null }
  published_at: string | null
  keyword_score: number
  semantic_score: number | null
  relevance_score: number
  score_explanation: string
  usage_status: string
}

export interface SearchResponse {
  items: SearchItem[]
  mode: 'hybrid' | 'keyword_only'
  degraded: boolean
  degradation_reason: string | null
}

export interface SearchRequest {
  query: string
  scope: 'current' | 'all'
  keyword_mode: 'hybrid' | 'keyword_only'
  top_k: number
  min_relevance: number
  statuses?: string[]
  from?: string
  to?: string
}

export interface MaterialArticleReference {
  article_id: string; article_title: string; article_revision_id: string; material_revision_id: string; used_at: string
}

export const materialsApi = {
  search: (payload: SearchRequest) =>
    apiRequest<SearchResponse>('/materials/search', { method: 'POST', body: payload }),
  list: (
    page: number,
    pageSize: number,
    params: { usageStatus?: string; categoryId?: string; tagId?: string; keyword?: string; favoriteMine?: boolean } = {},
  ) =>
    apiRequest<PaginatedResponse_MaterialOut_>(
      `/materials?${pageQuery(page, pageSize, {
        usage_status: params.usageStatus,
        category_id: params.categoryId,
        tag_id: params.tagId,
        keyword: params.keyword,
        favorite_mine: params.favoriteMine ? 'true' : undefined,
      })}`,
    ),
  create: (payload: MaterialCreateIn) =>
    apiRequest<MaterialOut>('/materials', { method: 'POST', body: payload }),
  createFromLink: (payload: MaterialLinkIn) =>
    apiRequest<MaterialOut>('/materials/from-link', { method: 'POST', body: payload }),
  createFromUpload: (payload: MaterialUploadIn) =>
    apiRequest<MaterialOut>('/materials/from-upload', { method: 'POST', body: payload }),
  get: (id: string) => apiRequest<MaterialDetailOut>(`/materials/${id}`),
  articles: (id: string) => apiRequest<MaterialArticleReference[]>(`/materials/${id}/articles`),
  update: (id: string, payload: MaterialUpdateIn) =>
    apiRequest<MaterialDetailOut>(`/materials/${id}`, { method: 'PATCH', body: payload }),
  remove: (id: string) => apiRequest(`/materials/${id}`, { method: 'DELETE' }),
  bulk: (payload: { material_ids: string[]; action: string; category_id?: string | null; tag_ids?: string[] }) =>
    apiRequest<BulkActionOut>('/materials/bulk', { method: 'POST', body: payload }),

  listCategories: () => apiRequest<MaterialCategoryOut[]>('/materials/categories'),
  createCategory: (payload: { name: string; parent_id?: string | null }) =>
    apiRequest<MaterialCategoryOut>('/materials/categories', { method: 'POST', body: payload }),
  listTags: () => apiRequest<TagOut[]>('/materials/tags'),
  createTag: (payload: { name: string }) =>
    apiRequest<TagOut>('/materials/tags', { method: 'POST', body: payload }),
  renameTag: (id: string, payload: { name: string }) =>
    apiRequest<TagOut>(`/materials/tags/${id}`, { method: 'PATCH', body: payload }),
  deleteTag: (id: string) => apiRequest(`/materials/tags/${id}`, { method: 'DELETE' }),

  favorite: (id: string) => apiRequest(`/materials/${id}/favorite`, { method: 'PUT' }),
  unfavorite: (id: string) => apiRequest(`/materials/${id}/favorite`, { method: 'DELETE' }),
}
