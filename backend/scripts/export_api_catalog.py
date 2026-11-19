"""Generate the implemented route/permission/CSRF contract directly from FastAPI."""
import inspect
import json
from pathlib import Path
from fastapi.routing import APIRoute
from app.config import Settings
from app.main import create_app


def main():
    app = create_app(Settings(APP_SECRET_KEY='catalog-only-'+'x'*40))
    spec = app.openapi()
    records = []
    def dependencies(node):
        result = []
        for child in node.dependencies:
            call = child.call
            name = getattr(call,'__name__','')
            closure = inspect.getclosurevars(call).nonlocals if inspect.isfunction(call) else {}
            result.append((name,closure.get('code')))
            result.extend(dependencies(child))
        return result
    def routes(items):
        for route in items:
            if hasattr(route,'effective_candidates'):
                yield from routes(route.effective_candidates())
            else:
                yield route
    for route in routes(app.routes):
        if not hasattr(route,'dependant'):
            continue
        deps = dependencies(route.dependant)
        for method in sorted(route.methods):
            operation = spec.get('paths',{}).get(route.path,{}).get(method.lower())
            assert operation is not None or not route.include_in_schema
            records.append({'method':method,'path':route.path,'authentication':'session' if any(name=='current_user' for name,_ in deps) else 'public','permissions':sorted({str(code) for _,code in deps if code is not None}),'csrf':any(name=='verify_csrf' for name,_ in deps),'responses':sorted(operation['responses']) if operation else ['200'],'request_schema':operation.get('requestBody',{}) if operation else {},'response_schema':operation['responses'] if operation else {},'in_openapi':route.include_in_schema})
            if method == 'GET' and route.path == '/api/v1/assistance/runs/{run_id}':
                records[-1]['permission_conditions'] = {'owner_only': True, 'by_kind': {'topic': ['creation:write', 'material:read', 'article:read'], 'relation': ['material:read', 'material:search'], 'search': ['material:read', 'material:search'], 'quality': ['article:read', 'material:read']}}
    assert len(records) > 100, 'Route traversal did not cover the implemented API'
    for row in records:
        if row['method'] in {'POST','PUT','PATCH','DELETE'} and row['path']!='/api/v1/auth/login' and '410' not in row['responses']:
            assert row['authentication']=='session' and row['csrf'], f"Unprotected mutation: {row['method']} {row['path']}"
    assert {(row['path'],row['method'].lower()) for row in records if row['in_openapi']} == {(path,method) for path,methods in spec['paths'].items() for method in methods if method in {'get','post','put','patch','delete','head','options'}}
    root = Path(__file__).resolve().parents[2]
    target = root/'doc/architecture/api-catalog.json'
    target.write_text(json.dumps({'routes':records,'components':spec['components']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines = ['# 已实现 API 与权限矩阵','','由 `backend/scripts/export_api_catalog.py` 从路由依赖和 OpenAPI 生成。字段及状态码完整快照见 `api-catalog.json`。','', '| 方法 | 路径 | 会话 | 权限（全部满足） | CSRF | 状态码 |','| --- | --- | --- | --- | --- | --- |']
    for row in records:
        lines.append('| '+ ' | '.join([row['method'],row['path'],row['authentication'],', '.join(row['permissions']) or '—','是' if row['csrf'] else '否',', '.join(row['responses'])])+' |')
    (root/'doc/architecture/api-permissions.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    with (root/'doc/architecture/api-permissions.md').open('a',encoding='utf-8') as output:
        output.write('\n“—”表示路由依赖未声明额外权限码，不代表没有动态权限或对象级检查。GET /api/v1/assistance/runs/{run_id} 仅限本人，按记录类型额外要求：topic 为 creation:write、material:read、article:read；relation 和 search 为 material:read、material:search；quality 为 article:read、material:read。异步作业限本人创建，上传授权与完成限本人，文件下载限上传者或已取得对应资源访问权。公开 OAuth 占位路径固定返回410，直连模式不会执行授权副作用。图片访问返回307短期重定向，报表导出为text/csv。\n')
    print(f'Exported {len(records)} implemented method/path contracts')


if __name__ == '__main__':
    main()
