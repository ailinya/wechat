"""Shared helpers strictly pinned to the disposable acceptance project."""
import json
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime,timezone

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/'doc/development/release-evidence'


def environment():
    values=dotenv_values(ROOT/'.acceptance/stack.env')
    if values.get('STACK_NAME')!='wetchat-acceptance' or values.get('POSTGRES_DB')!='wetchat_acceptance':
        raise RuntimeError('Only the isolated acceptance project is allowed')
    return values


def engine(database='wetchat_acceptance'):
    if not database.startswith('wetchat_acceptance'):
        raise RuntimeError('Refusing a non-acceptance database')
    values=environment()
    return create_engine(URL.create('postgresql+psycopg',username='wetchat',password=values['POSTGRES_PASSWORD'],host='127.0.0.1',port=int(values['POSTGRES_PORT']),database=database),pool_pre_ping=True,connect_args={'connect_timeout':5})


def compose(*args,check=True,capture=True):
    command=['docker','compose','--env-file',str(ROOT/'.acceptance/stack.env'),'-f',str(ROOT/'deploy/compose.yml'),'-f',str(ROOT/'deploy/compose.acceptance.yml'),*args]
    result=subprocess.run(command,cwd=ROOT,capture_output=capture,text=True,encoding='utf-8',errors='replace')
    if check and result.returncode:
        raise RuntimeError('Isolated compose operation failed: '+' '.join(args[:3])+' '+(result.stderr or '')[-500:])
    return result


def client():
    values=environment()
    result=httpx.Client(base_url='http://127.0.0.1:'+values['WEB_PORT'],timeout=30,trust_env=False)
    wait_until(lambda:result.get('/ready').status_code==200)
    login=result.post('/api/v1/auth/login',json={'account':'admin','password':values['WETCHAT_ADMIN_PASSWORD']})
    assert login.status_code==200,f'Acceptance administrator login failed ({login.status_code})'
    result.headers['X-CSRF-Token']=result.cookies['wetchat_csrf']
    return result


def api(client,path,method='GET',body=None,expected=(200,201,202,204),headers=None):
    prefix='http://127.0.0.1:58019' if path.startswith('/__acceptance__/') else '/api/v1'
    response=client.request(method,prefix+path,json=body,headers=headers)
    assert response.status_code in expected,f'{method} {path} returned {response.status_code}: {response.text[:400]}'
    return response.json() if response.content else None


def wait_until(work,predicate=lambda value:bool(value),timeout=90):
    end=time.monotonic()+timeout
    last=None
    while time.monotonic()<end:
        try:
            last=work()
            if predicate(last):
                return last
        except (httpx.HTTPError,ConnectionError):
            pass
        time.sleep(.4)
    raise AssertionError('Acceptance condition timed out: '+str(last)[:300])


def wait_job(c,job_id,expected='succeeded'):
    row=wait_until(lambda:api(c,'/async-jobs/'+str(job_id)),lambda r:r['status'] in ('succeeded','failed','cancelled'))
    assert row['status']==expected,f"Job {job_id} is {row['status']} ({row.get('last_error')})"
    return row


def save(name,value):
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    value={'checked_at':datetime.now(timezone.utc).isoformat(),**value}
    (EVIDENCE/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'evidence':name,**{k:v for k,v in value.items() if k in ('passed','checks','material_count','chunk_count','duration_seconds')}},ensure_ascii=False),flush=True)


CHECKS={key:'pass' for key in ['title','content','facts','citations','image_copyright','account_compliance','layout']}


def approve(c,article_id,revision_id):
    api(c,f'/articles/{article_id}/submit-review','POST',{'base_revision_id':revision_id})
    return api(c,f'/article-revisions/{revision_id}/reviews','POST',{'action':'approve','checklist':CHECKS})
