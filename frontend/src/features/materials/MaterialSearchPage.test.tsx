import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { MaterialSearchPage } from './MaterialSearchPage'
import { materialsApi } from '../../shared/api/materials'
import { creationApi } from '../../shared/api/creation'

vi.mock('../../app/AuthContext', () => ({ useAuth: () => ({ hasPermission: () => true, user: { id: 'editor' } }) }))
vi.mock('../../shared/api/materials', () => ({ materialsApi: { search: vi.fn() } }))
vi.mock('../../shared/api/creation', () => ({ creationApi: { models: vi.fn(), create: vi.fn() } }))

const item = { material_id: 'm1', title: '动力电池', matched_revision_id: 'r1', snippet: '电池回收与再生', source: { type: 'collection', title: '来源', url: 'https://example.org', attachment_id: null }, published_at: null, keyword_score: .5, semantic_score: null, relevance_score: .5, score_explanation: '关键词', usage_status: 'used' }

beforeEach(() => { sessionStorage.clear(); vi.clearAllMocks(); vi.mocked(creationApi.models).mockResolvedValue([{ id: 'model-1', name: '模型', model_name: 'model' }]) })

it('保留主题和候选选择，可查询全库并移除候选', async () => {
  vi.mocked(materialsApi.search).mockResolvedValue({ items: [item], mode: 'keyword_only', degraded: true, degradation_reason: 'embedding_unreachable' })
  const user = userEvent.setup()
  const view = render(<MaterialSearchPage topic />)
  await user.type(screen.getByLabelText('创作主题'), '动力电池')
  await user.selectOptions(screen.getByLabelText('范围'), 'all')
  await user.click(screen.getByRole('button', { name: '检索' }))
  expect(await screen.findByText(/语义检索暂不可用/)).toBeInTheDocument()
  expect(materialsApi.search).toHaveBeenCalledWith(expect.objectContaining({ query: '动力电池', scope: 'all' }))
  await user.click(screen.getByRole('checkbox', { name: '选择' }))
  expect(screen.getByText(/已选择素材（1）/)).toBeInTheDocument()
  view.unmount()
  render(<MaterialSearchPage topic />)
  expect(screen.getByLabelText('创作主题')).toHaveValue('动力电池')
  expect(screen.getByText(/已选择素材（1）/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '移除' }))
  expect(screen.getByText(/已选择素材（0）/)).toBeInTheDocument()
})

it('素材创作提交明确选择的素材和修订', async () => {
  vi.mocked(materialsApi.search).mockResolvedValue({ items: [item], mode: 'keyword_only', degraded: false, degradation_reason: null })
  vi.mocked(creationApi.create).mockResolvedValue({ resource_id: 'task-1', async_job_id: 'job-1', status: 'pending', reused: false, decision: null })
  const user = userEvent.setup()
  render(<MaterialSearchPage topic materialMode />)
  await user.type(screen.getByLabelText('关键词'), '电池')
  await user.click(screen.getByRole('button', { name: '检索' }))
  await user.click(await screen.findByRole('checkbox', { name: '选择' }))
  await screen.findByRole('option', { name: '模型（model）' })
  await user.click(screen.getByRole('button', { name: '提交创作' }))
  expect(creationApi.create).toHaveBeenCalledWith(expect.objectContaining({ mode: 'material', topic: '', materials: [{ material_id: 'm1', revision_id: 'r1' }] }), expect.any(String))
})
