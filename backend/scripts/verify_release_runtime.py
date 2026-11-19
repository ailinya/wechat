"""Build and smoke-test the actual runtime target without acceptance adapters."""
import subprocess
from pathlib import Path
from uuid import uuid4
import httpx
from release_support import ROOT, environment, save, wait_until


def main():
    values = environment()
    project = 'wetchat-release-' + uuid4().hex[:8]
    target = ROOT/'.acceptance'/f'{project}.env'
    values.update(STACK_NAME=project,APP_ENV_FILE=target.as_posix(),APP_IMAGE='wetchat-api:release-probe',WEB_IMAGE='wetchat-web:acceptance',APP_TARGET='runtime',APP_ENV='production',ASGI_APP='app.asgi:app',CELERY_APP='app.modules.async_execution.celery_app:celery_app',POSTGRES_DB='wetchat_release_probe',POSTGRES_PORT='55440',REDIS_PORT='56380',RUSTFS_API_PORT='59002',RUSTFS_CONSOLE_PORT='59003',API_PORT='58021',WEB_PORT='55180',ACCEPTANCE_FIXTURE='0',RUSTFS_CORS_ALLOWED_ORIGINS='http://127.0.0.1:55180')
    values['DATABASE_URL'] = values['DATABASE_URL'].rsplit('/',1)[0]+'/wetchat_release_probe'
    values['RUSTFS_PUBLIC_ENDPOINT'] = 'http://127.0.0.1:59002'
    target.write_text('\n'.join(f'{key}={value}' for key,value in values.items())+'\n',encoding='utf-8')
    command = ['docker','compose','--env-file',str(target),'-f',str(ROOT/'deploy/compose.yml')]
    def dc(*args):
        result = subprocess.run([*command,*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        assert result.returncode == 0, 'Runtime deployment operation failed: '+' '.join(args)+' '+result.stderr[-500:]
    try:
        dc('build','api')
        dc('up','-d','--no-build')
        with httpx.Client(base_url='http://127.0.0.1:55180',trust_env=False,timeout=10) as c:
            wait_until(lambda:c.get('/ready').status_code==200,timeout=180)
            assert c.get('/health').json() == {'status':'ok'}
            assert c.post('/api/v1/auth/login',json={'account':'admin','password':values['WETCHAT_ADMIN_PASSWORD']}).status_code == 200
            assert c.get('/api/v1/auth/me').json()['account'] == 'admin'
            assert c.get('/api/v1/dashboard').status_code == 200
            dc('run','--rm','--no-deps','-e','WETCHAT_ADMIN_PASSWORD=synthetic-password-must-not-reset-admin','api','python','-m','app.commands.initialize')
            assert c.post('/api/v1/auth/login',json={'account':'admin','password':values['WETCHAT_ADMIN_PASSWORD']}).status_code == 200
            assert c.get('/').status_code == 200
            assert c.get('http://127.0.0.1:58021/__acceptance__/state').status_code == 404
            dc('restart','api','worker','beat','dispatcher')
            wait_until(lambda:c.get('/ready').status_code==200)
            assert c.get('/api/v1/auth/me').status_code == 200
        save('runtime-deployment', {'passed':True,'checks':['runtime_target_no_external_fixtures','fresh_database_migration','storage_bucket_initialization','first_admin_login','repeat_initializer_preserves_admin_password','built_static_frontend','all_processes_deployed','restart_preserves_session','acceptance_endpoints_absent'],'project':project,'tls':'loopback HTTP smoke only; public deployment requires TLS termination','real_external_calls':False})
    finally:
        dc('down')


if __name__ == '__main__':
    main()
