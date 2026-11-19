from acceptance.adapters import install, state
install()

import io
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from app.main import create_app
from app.api.deps import DbSession, require_permission, verify_csrf
from app.schemas.auth import PermissionCode
from app.config import load_settings
from app.adapters.object_storage import _client

app = create_app()


@app.get('/__acceptance__/state')
def acceptance_state(user=Depends(require_permission(PermissionCode.SETTINGS_READ))):
    return state(lambda current:{'draft_writes':current.get('draft_writes',0),'faults':current.get('faults',{})})


class Faults(BaseModel):
    model_timeout: bool = False
    wechat_timeout_once: bool = False
    slow_model_seconds:float=Field(default=0,ge=0,le=30)


@app.post('/__acceptance__/faults')
def faults(payload:Faults,user=Depends(require_permission(PermissionCode.SETTINGS_WRITE)),csrf=Depends(verify_csrf)):
    def change(current):
        current['faults']=payload.model_dump()
        return current['faults']
    return state(change)


@app.post('/__acceptance__/health-job',status_code=202)
def health_job(db:DbSession,user=Depends(require_permission(PermissionCode.SETTINGS_WRITE)),csrf=Depends(verify_csrf)):
    from uuid import uuid4
    from app.services.wechat_account_service import enqueue
    resource=uuid4()
    job=enqueue(db.connection(),'system.healthcheck','system_healthcheck',resource,{},user.id)
    db.commit()
    return {'async_job_id':job,'resource_id':resource,'status':'pending'}


@app.post('/__acceptance__/cover')
def cover(db:DbSession,user=Depends(require_permission(PermissionCode.ARTICLE_WRITE)),csrf=Depends(verify_csrf)):
    import base64,hashlib
    from uuid import uuid4
    data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1kAAAAASUVORK5CYII=')
    key='acceptance/'+uuid4().hex+'.png'
    settings=load_settings()
    _client(settings).put_object(settings.rustfs_bucket,key,io.BytesIO(data),len(data),content_type='image/png')
    result=db.connection().execute(text('INSERT INTO stored_objects(bucket,object_key,content_type,size_bytes,sha256,uploader_id) VALUES (:bucket,:key,\'image/png\',:size,:sha,:user) RETURNING id'),{'bucket':settings.rustfs_bucket,'key':key,'size':len(data),'sha':hashlib.sha256(data).hexdigest(),'user':user.id}).scalar_one()
    db.commit()
    return {'id':result}
