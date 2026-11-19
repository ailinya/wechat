"""Check edge/API JSON correlation and absence of raw query credentials."""
import json
import subprocess
import time
from uuid import uuid4

import httpx
from release_support import environment, save


def main():
    values = environment()
    marker = 'acceptance-log-token-'+uuid4().hex
    with httpx.Client(trust_env=False,timeout=10) as c:
        response = c.get('http://127.0.0.1:'+values['WEB_PORT']+'/health',params={'access_token':marker})
        assert response.status_code == 200
        request_id = response.headers['x-request-id']
    time.sleep(.3)
    counts = {}
    for name in ['api','web']:
        result = subprocess.run(['docker','logs','--since','30s','wetchat-acceptance-'+name+'-1'],capture_output=True,text=True,encoding='utf-8',errors='replace')
        assert result.returncode == 0
        logs = result.stdout+'\n'+result.stderr
        assert marker not in logs, name+' exposed a raw query token'
        rows = [json.loads(line) for line in logs.splitlines() if line.startswith('{')]
        assert any(row.get('request_id')==request_id and row.get('path')=='/health' for row in rows), name+' did not correlate the request'
        counts[name] = len(rows)
    save('deployed-logging',{'passed':True,'checks':['api_logging_records_json','nginx_access_records_json','request_id_correlates_edge_and_api_response','route_path_without_query','raw_query_token_absent','uvicorn_duplicate_raw_access_disabled'],'parsed_records':counts,'unmanaged_startup_output':'Entrypoint output and optional urllib3 SOCKS dependency warning are outside structured business logs'})


if __name__ == '__main__':
    main()
