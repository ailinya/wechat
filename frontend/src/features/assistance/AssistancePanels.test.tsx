import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { assistanceApi } from '../../shared/api/assistance'
import { QualityPanel, RelationPanel, ReusePanel, TopicPanel } from './AssistancePanels'

vi.mock('../../shared/api/assistance', () => ({ assistanceApi: { models: vi.fn(), topics: vi.fn(), quality: vi.fn(), relations: vi.fn(), generateRelations: vi.fn(), ignore: vi.fn(), reuse: vi.fn() } }))
const api = vi.mocked(assistanceApi)
beforeEach(() => { vi.resetAllMocks(); api.models.mockResolvedValue([{ id: 'model', name: '分析模型', model_name: 'fixture' }]) })

it('主题建议展示依据和重复文章，由用户决定采用', async () => {
  const choose = vi.fn(), user = userEvent.setup()
  api.topics.mockResolvedValue({ id: 'run', status: 'succeeded', error_code: null, usage: {}, result: { candidates: [{ title: '电池回收', rationale: '基于素材', evidence: [{ material_id: 'm', revision_id: 'r', quote: '来源正文', source_url: null }], duplicate_articles: [{ id: 'a', revision_id: 'ar', title: '电池回收' }] }] } })
  render(<TopicPanel materialIds={['m']} onChoose={choose} />)
  await user.click(screen.getByRole('button', { name: '准备主题推荐' }))
  await user.selectOptions(await screen.findByLabelText('分析模型'), 'model')
  await user.click(screen.getByRole('button', { name: '生成主题建议' }))
  expect(await screen.findByText(/已有同标题文章/)).toBeInTheDocument()
  expect(screen.getByText(/来源正文/)).toBeInTheDocument()
  expect(choose).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '采用此主题' }))
  expect(choose).toHaveBeenCalledWith('电池回收')
})

it('关联建议可忽略并显示处理状态', async () => {
  const user = userEvent.setup()
  const item = { id: 's', target_material_id: 'm2', target_revision_id: 'r2', target_title: '历史资料', score: .8, is_current: true, ignored_at: null, evidence: { snippet: '关联依据', score_explanation: '关键词', mode: 'keyword_only' } }
  api.relations.mockResolvedValueOnce([item]).mockResolvedValueOnce([{ ...item, ignored_at: '2026-01-01' }])
  api.ignore.mockResolvedValue({})
  render(<RelationPanel materialId="m1" canWrite />)
  await user.click(screen.getByRole('button', { name: '查看建议' }))
  expect(await screen.findByText(/关联依据/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '忽略建议' }))
  expect(await screen.findByText(/已忽略/)).toBeInTheDocument()
})

it('模型失败时明确提示仍可编辑审核', async () => {
  const user = userEvent.setup()
  api.quality.mockResolvedValue({ id: 'run', status: 'failed', error_code: 'model_unreachable', usage: {}, result: {} })
  render(<QualityPanel articleId="a" revisionId="r" />)
  await user.click(screen.getByRole('button', { name: '准备质量评估' }))
  await user.selectOptions(await screen.findByLabelText('分析模型'), 'model')
  await user.click(screen.getByRole('button', { name: '评估当前修订' }))
  expect(await screen.findByText(/仍可继续编辑和审核/)).toBeInTheDocument()
})

it('账号指标缺失显示不可用而非零', async () => {
  const user = userEvent.setup()
  api.reuse.mockResolvedValue({ total: 1, page: 1, page_size: 20, definition: '全历史', items: [{ id: 'm', title: '素材', articles: 2, article_revisions: 3, accounts: [{ id: 'a', name: '账号', publish_orders: 2, publish_attempts: 3, draft_deliveries: 0, draft_attempts: 0, manual_publications: 0, metrics_status: 'unavailable', metrics_note: '微信指标不可用', metric_snapshots: [] }] }] })
  render(<ReusePanel />)
  await user.click(screen.getByRole('button', { name: '查看复用报表' }))
  expect(await screen.findByText(/微信指标不可用/)).toBeInTheDocument()
  expect(screen.getByText(/发布单 2，发布尝试 3/)).toBeInTheDocument()
})
