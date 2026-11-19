import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { CreationPage } from './CreationPage'
import { creationApi } from '../../shared/api/creation'

vi.mock('../../app/AuthContext', () => { const hasPermission = () => true; return { useAuth: () => ({ hasPermission }) } })
vi.mock('../materials/MaterialSearchPage', () => ({ MaterialSearchPage: () => <p>素材检索</p> }))
vi.mock('../../shared/api/creation', () => ({ creationApi: { tasks: vi.fn(), rules: vi.fn(), models: vi.fn(), targetAccounts: vi.fn(), task: vi.fn(), outputs: vi.fn(), changeRule: vi.fn(), action: vi.fn() } }))
vi.mock('../../shared/api/collection', () => ({ collectionApi: { listTasks: vi.fn().mockResolvedValue({ items: [] }) } }))

const api = vi.mocked(creationApi)
const rule = { id: 'rule-1', name: '原规则', topic: '行业', trigger_type: 'manual', material_strategy: 'new_only', enabled: true, model_config_id: 'model-1', collection_task_ids: [], trigger_config: { cron: null, timezone: 'Asia/Shanghai', new_material_threshold: 1 }, min_new_material_count: 0, min_material_count: 1, min_relevance: 0, reference_count: 3, batch_count: 1, article_type: 'news', writing_style: '客观', min_words: 300, max_words: 1200, prompt: '', require_analysis: false }
const task = { id: 'task-1', rule_id: null, source_task_id: null, mode: 'topic', topic: '主题', status: 'insufficient', trigger_type: 'manual', trigger_source: null, trigger_window: '1', error_code: null, decision: { status: 'insufficient', reasons: ['material_count_insufficient'], details: {} }, materials: [], candidates: [], created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }

beforeEach(() => {
  vi.clearAllMocks()
  api.tasks.mockResolvedValue({ items: [task], total: 1, page: 1, page_size: 100 })
  api.rules.mockResolvedValue({ items: [rule], total: 1, page: 1, page_size: 100 })
  api.models.mockResolvedValue([{ id: 'model-1', name: '生成', model_name: 'model' }])
  api.targetAccounts.mockResolvedValue([])
  api.task.mockResolvedValue(task)
  api.outputs.mockResolvedValue([])
  api.changeRule.mockResolvedValue(rule)
})

it('重新打开并保存已有规则', async () => {
  window.location.hash = '#/creation?view=rules'
  const user = userEvent.setup()
  render(<CreationPage />)
  await user.click(await screen.findByRole('button', { name: '编辑' }))
  expect(screen.getByLabelText('规则名称')).toHaveValue('原规则')
  await user.clear(screen.getByLabelText('规则名称'))
  await user.type(screen.getByLabelText('规则名称'), '更新规则')
  await user.click(screen.getByRole('button', { name: '保存规则' }))
  await waitFor(() => expect(api.changeRule).toHaveBeenCalledWith('rule-1', expect.objectContaining({ name: '更新规则', material_strategy: 'new_only' })))
})

it('展示不足原因并链接真实产物', async () => {
  window.location.hash = '#/creation?view=tasks&task_id=task-1'
  api.outputs.mockResolvedValue([{ id: 'output-1', slot: 1, article_id: 'article-1', article_revision_id: 'rev-1', title: '标题', candidate_titles: ['候选'], summary: '摘要', outline: ['大纲'], body_markdown: '正文', keywords: ['关键词'], cover_suggestion: '封面建议', citations: [] }])
  render(<CreationPage />)
  expect(await screen.findByText('条件不足：素材数量不足')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看待审核文章' })).toHaveAttribute('href', '#/content/articles/article-1')
})
