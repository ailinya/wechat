"""Bounded, credential-free dependency probes, separate from liveness."""
import time
from functools import lru_cache
from pathlib import Path

import redis
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.adapters.object_storage import probe


@lru_cache(maxsize=8)
def probe_engine(url):
    return create_engine(url, pool_size=1, max_overflow=0, pool_timeout=2, pool_pre_ping=True, connect_args={'connect_timeout':2,'options':'-c statement_timeout=2000'})


@lru_cache(maxsize=1)
def schema_head():
    cfg = Config(str(Path(__file__).resolve().parents[2]/'alembic.ini'))
    cfg.set_main_option('script_location',str(Path(__file__).resolve().parents[2]/'alembic'))
    return ScriptDirectory.from_config(cfg).get_current_head()


def check(settings):
    checks = {}
    for name in ['database','broker','storage']:
        started = time.monotonic()
        try:
            if name == 'database':
                if not settings.database_url:
                    raise ValueError()
                with probe_engine(settings.database_url).connect() as conn:
                    version = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                    if version != schema_head():
                        raise ValueError()
            elif name == 'broker':
                with redis.Redis.from_url(settings.redis_url,socket_timeout=2,socket_connect_timeout=2) as client:
                    client.ping()
            elif not probe(settings)['reachable']:
                raise ValueError()
            checks[name] = {'ready':True,'error_code':None,'latency_ms':round((time.monotonic()-started)*1000,2)}
        except Exception:
            checks[name] = {'ready':False,'error_code':name+'_unavailable','latency_ms':round((time.monotonic()-started)*1000,2)}
    return {'status':'ready' if all(item['ready'] for item in checks.values()) else 'degraded','checks':checks}
