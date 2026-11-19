import json
import os
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text


def guard():
    if os.environ.get('APP_ENV')!='test' or os.environ.get('ACCEPTANCE_FIXTURE')!='1' or not any(os.environ.get('DATABASE_URL','').endswith('/'+name) for name in ['wetchat_acceptance','wetchat_acceptance_perf','wetchat_acceptance_restore']):
        raise RuntimeError('Acceptance adapters require the explicit isolated test stack')


def state(operation):
    from app.config import load_settings
    from app.database import get_engine
    with get_engine(load_settings()).begin() as conn:
        conn.execute(text("INSERT INTO system_settings(key,value) VALUES ('acceptance.remote','{}') ON CONFLICT DO NOTHING"))
        current = conn.execute(text("SELECT value FROM system_settings WHERE key='acceptance.remote' FOR UPDATE")).scalar_one()
        result = operation(current)
        conn.execute(text("UPDATE system_settings SET value=CAST(:value AS jsonb),updated_at=now() WHERE key='acceptance.remote'"),{'value':json.dumps(current,ensure_ascii=False)})
        return result


def fault(name):
    return state(lambda current:current.get('faults',{}).get(name,False))


def install():
    guard()
    from app.adapters import embedding_client, source_fetch, wechat_client, model_client
    def embed(texts,**kwargs):
        if len(texts)==1 and texts[0].startswith('palette_') and texts[0][8:].isdigit():
            from app.config import load_settings
            from app.database import get_engine
            with get_engine(load_settings()).connect() as conn:
                value=conn.execute(text('SELECT embedding::text FROM acceptance_vector_palette WHERE id=:id'),{'id':int(texts[0][8:])}).scalar_one()
            return [json.loads(value)],{'fixture':True}
        return [[1.0]+[0.0]*1023 for _ in texts],{'fixture':True}
    embedding_client.embed_texts = embed
    def resolver(host,port):
        if host!='acceptance.example.test':
            raise source_fetch.FetchError('fixture_host_denied','Acceptance only allows synthetic source hosts')
        return ['93.184.216.34']
    source_fetch._default_resolver = resolver
    def fetch_transport(url,timeout):
        if urlsplit(url).hostname!='acceptance.example.test':
            raise source_fetch.FetchError('fixture_host_denied','Synthetic source required')
        content = '<html><head><meta property="article:published_time" content="2026-11-19T00:00:00+08:00"><title>[fixture] 电池回收试点</title></head><body><article><h1>[fixture] 电池回收试点</h1><p>发布时间：2026-11-19</p>'+''.join('<p>这是验收合成素材。星河实验室电池回收试点每月处理100吨旧电池，材料包含锂和镍。数据仅用于独立环境的流程验证。第'+str(i)+'段。</p>' for i in range(20))+'</article></body></html>'
        return 200,{'content-type':'text/html; charset=utf-8'},content.encode()
    source_fetch._default_transport = fetch_transport
    def generate(self,config,*,topic,materials,options):
        import time
        delay=fault('slow_model_seconds')
        if delay:
            time.sleep(min(float(delay),30))
        if fault('model_timeout'):
            raise model_client.ModelError('model_unreachable','[fixture] model timeout')
        from app.schemas.creation import GeneratedDraft
        return {'draft':GeneratedDraft(title='[fixture] 电池回收进展',candidate_titles=['回收试点'],summary='合成样例，仅供验收',outline=['试点进展'],body_markdown='# 合成验收文章\n\n'+('星河实验室电池回收试点每月处理100吨旧电池。此数字为测试样例，文章由确定性模型替身生成。\n\n'*8),keywords=['电池','回收'],cover_suggestion='测试封面',citations=[{'material_id':str(m['material_id']),'revision_id':str(m['revision_id'])} for m in materials]),'usage':{'fixture':True}}
    model_client.ModelClient.generate = generate
    def wechat(path,payload,token=None,upload=None):
        if path=='/cgi-bin/stable_token':
            if payload.get('appid')!='wx0123456789abcdef' or payload.get('secret')!='acceptance-only-not-real-secret':
                return {'errcode':40125}
            return {'access_token':'acceptance-not-a-real-token','expires_in':7200}
        if path=='/cgi-bin/freepublish/batchget' or path=='/cgi-bin/freepublish/submit':
            return {'errcode':48001}
        if path in ('/cgi-bin/material/add_material','/cgi-bin/media/uploadimg'):
            return {'media_id':'fixture-cover','url':'https://mmbiz.qpic.cn/fixture.png'}
        if path=='/cgi-bin/draft/add':
            def write(current):
                drafts=current.setdefault('drafts',{})
                media='fixture-draft-'+uuid4().hex
                drafts[media]={'media_id':media,'content':{'news_item':payload['articles']}}
                current['draft_writes']=current.get('draft_writes',0)+1
                timeout=current.setdefault('faults',{}).pop('wechat_timeout_once',False)
                return media,timeout
            media,timeout=state(write)
            if timeout:
                raise wechat_client.WechatError('wechat_unreachable',uncertain=True)
            return {'media_id':media}
        if path=='/cgi-bin/draft/batchget':
            items=state(lambda current:list(current.get('drafts',{}).values()))
            offset=payload.get('offset',0)
            return {'total_count':len(items),'item':items[offset:offset+payload.get('count',20)]}
        return {'total_count':0,'item':[]}
    wechat_client.http_transport = wechat
