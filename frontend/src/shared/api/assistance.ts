import { apiRequest } from './client'
import type { SearchRequest, SearchResponse } from './materials'

export interface AnalysisModel { id: string; name: string; model_name: string }
export interface Evidence { material_id: string; revision_id: string; quote: string; source_url: string | null }
export interface Topic { title: string; rationale: string; evidence: Evidence[]; duplicate_articles: { id: string; revision_id: string; title: string }[] }
export interface QualityIssue { category: string; advice: string; limitation: string; evidence: { article_quote: string; material_id?: string; revision_id?: string; source_quote?: string; source_url?: string | null } }
export interface Run { id: string; status: string; error_code: string | null; result: { candidates?: Topic[]; suggestions?: QualityIssue[]; limitation?: string }; usage: Record<string, number> }
export interface Relation { id: string; target_material_id: string; target_revision_id: string; target_title: string; score: number; is_current: boolean; ignored_at: string | null; evidence: { snippet: string; score_explanation: string; mode: string } }
export interface ReuseAccount { id: string; name: string; publish_orders: number; publish_attempts: number; draft_deliveries: number; draft_attempts: number; manual_publications: number; metrics_status: string; metrics_note: string; metric_snapshots: { external_article_id: string; collected_at: string; reads: number | null; likes: number | null; shares: number | null }[] }
export interface ReuseReport { items: { id: string; title: string; articles: number; article_revisions: number; accounts: ReuseAccount[] }[]; total: number; page: number; page_size: number; definition: string }

export const assistanceApi = {
  models: () => apiRequest<AnalysisModel[]>('/assistance/models'),
  topics: (model_config_id: string, material_ids: string[]) => apiRequest<Run>('/assistance/topics', { method: 'POST', body: { model_config_id, material_ids } }),
  quality: (article: string, revision_id: string, model_config_id: string) => apiRequest<Run>(`/assistance/articles/${encodeURIComponent(article)}/quality`, { method: 'POST', body: { revision_id, model_config_id } }),
  relations: (id: string) => apiRequest<Relation[]>(`/assistance/materials/${encodeURIComponent(id)}/relations`),
  generateRelations: (id: string) => apiRequest<{ items: Relation[]; degraded: boolean; degradation_reason: string | null }>(`/assistance/materials/${encodeURIComponent(id)}/relations`, { method: 'POST' }),
  ignore: (id: string) => apiRequest(`/assistance/relations/${encodeURIComponent(id)}/ignore`, { method: 'POST' }),
  search: (request: SearchRequest) => apiRequest<SearchResponse>('/assistance/search', { method: 'POST', body: { ...request, expand_relations: true } }),
  reuse: (page: number) => apiRequest<ReuseReport>(`/assistance/analytics/reuse?page=${page}&page_size=20`),
}
