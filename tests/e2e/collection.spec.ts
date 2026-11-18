import { expect,test } from '@playwright/test'

test('主题搜索无来源提交，刷新恢复结果视图和分析历史',async({page})=>{
  const empty={items:[],total:0,page:1,page_size:10}
  let submitted:Record<string,unknown>|null=null
  await page.route('**/api/v1/**',async route=>{
    const url=new URL(route.request().url());const path=url.pathname.replace('/api/v1','')
    let body:unknown=empty
    if(path==='/auth/me')body={id:'user',account:'admin',name:'管理员',roles:[],permissions:['collection:read','collection:write','collection:run','settings:read','settings:write','material:read','material:write']}
    else if(path==='/collection/config-options')body={searches:[{id:'search',name:'新闻搜索'}],models:[]}
    else if(path==='/collection/tasks'&&route.request().method()==='POST'){submitted=route.request().postDataJSON();body={id:'task',...submitted}}
    else if(path==='/collection/results')body={...empty,total:1,items:[{id:'result',run_id:'run',title:'人工智能新闻',url:'https://example.com/news',parse_status:'parsed',materialize_status:'pending'}]}
    else if(path.endsWith('/candidates'))body=[{id:'candidate',url:'https://example.com/news',status:'parsed',error:null,attempts:[{id:'attempt',stage:'parse',status:'succeeded',attempt:1}],snapshot:{markdown:'固定中文正文',extractor_version:'fixture/1',content_hash:'hash'}}]
    else if(path==='/collection/analysis')body={...empty,total:1,items:[{id:'analysis',result_id:'result',status:'failed',attempt:1,error:'invalid_citation',stale:false}]}
    else if(path.endsWith('/retry'))body={analysis_id:'analysis',async_job_id:'job',status:'accepted'}
    await route.fulfill({json:body})
  })
  await page.goto('/#/collection?view=tasks')
  await page.getByLabel('任务名称').fill('主题日报')
  await page.getByLabel('采集模式').selectOption('topic_search')
  await page.getByLabel('主题',{exact:true}).fill('人工智能')
  await page.locator('select[name="search"]').selectOption('search')
  await page.getByRole('button',{name:'新建任务',exact:true}).click()
  await expect.poll(()=>submitted).toMatchObject({mode:'topic_search',source_ids:[],topic:'人工智能'})
  await page.goto('/#/collection?view=results&run_id=run')
  await page.reload()
  await expect(page.getByRole('heading',{name:'候选与阶段'})).toBeVisible()
  await page.getByRole('button',{name:'分析详情'}).click()
  await expect(page.getByText('invalid_citation')).toBeVisible()
  await page.getByRole('button',{name:'重试分析'}).click()
  await expect(page.getByText('分析重试已受理')).toBeVisible()
  await page.screenshot({path:'test-results/collection-desktop.png',fullPage:true})
  await page.setViewportSize({width:390,height:844})
  await expect(page.getByRole('heading',{name:'素材分析',exact:true})).toBeVisible()
  await page.screenshot({path:'test-results/collection-mobile.png',fullPage:true})
})

test('无设置权限不能进入搜索模型配置',async({page})=>{
  await page.route('**/api/v1/auth/me',route=>route.fulfill({json:{id:'editor',account:'editor',name:'编辑',roles:[],permissions:['collection:read']}}))
  await page.goto('/#/settings')
  await expect(page.getByRole('heading',{name:'无访问权限'})).toBeVisible()
  await expect(page.getByRole('button',{name:'新增分析模型'})).toHaveCount(0)
})
