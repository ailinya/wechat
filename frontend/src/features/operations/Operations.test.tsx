import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { AnalyticsPage } from './AnalyticsPage'
import { NotificationsPanel } from './NotificationsPanel'
import { SettingsPage } from './SettingsPage'
import { DashboardHome } from '../dashboard/Home'
import { operationsApi } from '../../shared/api/operations'
import type { ReportOut } from '../../shared/api/types'

const state=vi.hoisted(()=>({permissions:new Set<string>(['analytics:read','analytics:export','account:read','article:read','settings:read','settings:write'])}))
vi.mock('../../app/AuthContext',()=>({useAuth:()=>({user:{name:'测试管理员'},hasPermission:(code:string)=>state.permissions.has(code)})}))
vi.mock('../../shared/api/operations',async original=>({...await original<typeof import('../../shared/api/operations')>(),operationsApi:{report:vi.fn(),export:vi.fn(),notifications:vi.fn(),preferences:vi.fn(),preference:vi.fn(),refreshNotifications:vi.fn(),readNotification:vi.fn(),platform:vi.fn(),savePlatform:vi.fn(),dashboard:vi.fn(),publicPlatform:vi.fn()}}))
vi.mock('../../shared/api/wechat',()=>({accountsApi:{list:vi.fn(async()=>({items:[],total:0,page:1,page_size:100}))}}))
const api=vi.mocked(operationsApi)
const stamp='2026-11-19T00:00:00Z'
const platform={name:'测试平台',description:'内容运营',brand_mark:'智',timezone:'Asia/Shanghai',version:1,updated_at:stamp}
const report:ReportOut={kind:'accounts',filters:{start_date:'2026-11-01',end_date:'2026-12-01',timezone:'Asia/Shanghai'},items:[{id:'r1',title:'个人号',status:'unavailable',source:'wechat_metrics',url:'/accounts?account_id=a1',occurred_at:stamp,account_id:'a1',metrics:{reads:{value:null,available:false,reason:'无权限'},likes:{value:null,available:false},shares:{value:0,available:true}}}],total:1,page:1,page_size:20,summary:{total:1,succeeded:0,failed:0,denominator:0,success_rate:null,attempts:0,quantity:1,reused_materials:0,by_status:{unavailable:1},by_source:{wechat_metrics:1},by_group:{个人号:1},failure_reasons:{},definition:'不可获取指标显示不可用'},trend:[{day:'2026-11-19',count:1}]}
beforeEach(()=>{vi.clearAllMocks();state.permissions=new Set(['analytics:read','analytics:export','account:read','article:read','settings:read','settings:write']);api.report.mockResolvedValue(report);api.export.mockResolvedValue();api.notifications.mockResolvedValue({items:[],total:0,page:1,page_size:10});api.preferences.mockResolvedValue([{category:'review',channel:'in_app',enabled:true}]);api.platform.mockResolvedValue(platform);api.publicPlatform.mockResolvedValue(platform);window.location.hash='#/analytics?kind=accounts&start_date=2026-11-01&end_date=2026-12-01'})

it('账号未知指标显示不可用，真实零仍显示零，导出保留URL筛选',async()=>{
  const user=userEvent.setup()
  render(<AnalyticsPage/> )
  expect(await screen.findByRole('link',{name:'个人号'})).toHaveAttribute('href','#/accounts?account_id=a1')
  expect(screen.getAllByRole('cell',{name:'不可用'}).length).toBeGreaterThanOrEqual(2)
  await user.click(screen.getByRole('button',{name:'导出当前筛选全部CSV'}))
  await waitFor(()=>expect(api.export).toHaveBeenCalled())
  const [kind,query]=api.export.mock.calls[0]
  expect(kind).toBe('accounts');expect(query.get('start_date')).toBe('2026-11-01');expect(query.has('page')).toBe(false)
})

it('通知标记已读和偏好变更通过本人API保存',async()=>{
  const user=userEvent.setup()
  api.notifications.mockResolvedValue({items:[{id:'n1',category:'review',title:'审核提醒',body:'pending_review',url:'/content/articles/one',occurred_at:stamp,created_at:stamp,read_at:null}],total:1,page:1,page_size:10})
  api.readNotification.mockResolvedValue({id:'n1',category:'review',title:'审核提醒',body:'pending_review',url:'/content/articles/one',occurred_at:stamp,created_at:stamp,read_at:stamp})
  api.preference.mockResolvedValue([{category:'review',channel:'in_app',enabled:false}])
  render(<NotificationsPanel preferences/> )
  await user.click(await screen.findByRole('button',{name:'标记已读'}));expect(api.readNotification).toHaveBeenCalledWith('n1')
  await user.click(screen.getByRole('checkbox',{name:'人工审核'}))
  await waitFor(()=>expect(api.preference).toHaveBeenCalledWith({category:'review',channel:'in_app',enabled:false}))
})

it('平台配置保存版本并有结果提示，无写权限隐藏保存按钮',async()=>{
  window.location.hash='#/settings?tab=platform'
  const user=userEvent.setup();api.savePlatform.mockResolvedValue({...platform,name:'新平台',version:2})
  const {unmount}=render(<SettingsPage/> )
  const name=await screen.findByLabelText('平台名称');await user.clear(name);await user.type(name,'新平台');await user.click(screen.getByRole('button',{name:'保存平台设置'}))
  await waitFor(()=>expect(api.savePlatform).toHaveBeenCalledWith(expect.objectContaining({name:'新平台',version:1})))
  expect(await screen.findByRole('status')).toHaveTextContent('平台设置已保存')
  unmount();state.permissions.delete('settings:write');render(<SettingsPage/> );await screen.findByLabelText('平台名称');expect(screen.queryByRole('button',{name:'保存平台设置'})).not.toBeInTheDocument()
})

it('工作台呈现业务事实和有权快捷入口，权限范围外数据不显示',async()=>{
  api.dashboard.mockResolvedValue({timezone:'Asia/Shanghai',as_of:stamp,counters:{pending_review:1,materials_total:null,published_articles:0},recent_articles:[{id:'a1',title:'待审核样例',status:'pending_review',url:'/content/articles/a1',occurred_at:stamp}],activity:[],todos:[],alerts:[]})
  render(<DashboardHome/> )
  expect(await screen.findByRole('heading',{name:'测试平台'})).toBeInTheDocument()
  expect(screen.getByRole('link',{name:'待审核样例'})).toHaveAttribute('href','#/content/articles/a1')
  expect(screen.queryByText('素材总数')).not.toBeInTheDocument()
  expect(screen.queryByRole('link',{name:'绑定公众号'})).not.toBeInTheDocument()
})
