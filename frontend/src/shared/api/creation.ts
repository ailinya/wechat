import { apiRequest } from './client'

export interface GenerationModel { id: string; name: string; model_name: string }
export interface CreationTask {
  id: string; rule_id: string | null; source_task_id: string | null; mode: string; topic: string; status: string
  trigger_type: string; trigger_source: string | null; trigger_window: string; error_code: string | null
  decision: { status: string; reasons: string[]; details: Record<string, unknown> } | null
  materials: { material_id: string; revision_id: string }[]; created_at: string; updated_at: string
  candidates: { material_id: string; revision_id: string; selected: boolean; relevance_score: number | null; selection_reason: string | null }[]
}
export interface CreationOutput {
  id: string; slot: number; article_id: string; article_revision_id: string; title: string
  candidate_titles: string[]; summary: string; outline: string[]; body_markdown: string; keywords: string[]
  cover_suggestion: string; citations: { material_id: string; revision_id: string }[]
}
export interface CreationAccepted { resource_id: string; async_job_id: string | null; status: string; reused: boolean; decision: CreationTask['decision'] }
export interface CreationRule {
  id: string; name: string; topic: string; trigger_type: string; material_strategy: string
  enabled: boolean; model_config_id: string; collection_task_ids: string[]
  trigger_config: { cron: string | null; timezone: string; new_material_threshold: number }
  min_new_material_count: number; min_material_count: number; min_relevance: number; reference_count: number
  batch_count: number; article_type: string; writing_style: string; min_words: number; max_words: number
  prompt: string; require_analysis: boolean
}
interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export const creationApi = {
  models: () => apiRequest<GenerationModel[]>('/creation-tasks/models'),
  create: (body: object, key: string) => apiRequest<CreationAccepted>('/creation-tasks', { method: 'POST', body, headers: { 'Idempotency-Key': key } }),
  tasks: () => apiRequest<Page<CreationTask>>('/creation-tasks?page_size=100'),
  task: (id: string) => apiRequest<CreationTask>(`/creation-tasks/${id}`),
  outputs: (id: string) => apiRequest<CreationOutput[]>(`/creation-tasks/${id}/outputs`),
  action: (id: string, action: 'cancel' | 'retry' | 'regenerate') => apiRequest<CreationAccepted | CreationTask>(`/creation-tasks/${id}/${action}`, { method: 'POST' }),
  rules: () => apiRequest<Page<CreationRule>>('/creation-rules?page_size=100'),
  saveRule: (body: object) => apiRequest<CreationRule>('/creation-rules', { method: 'POST', body }),
  changeRule: (id: string, body: object) => apiRequest<CreationRule>(`/creation-rules/${id}`, { method: 'PATCH', body }),
  runRule: (id: string, key: string) => apiRequest<CreationAccepted>(`/creation-rules/${id}/run`, { method: 'POST', headers: { 'Idempotency-Key': key } }),
}
