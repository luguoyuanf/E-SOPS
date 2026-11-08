#!/usr/bin/env python3
"""Independent black-box HTTP and read-only SQL evidence. Never imports app code.

Run from the repository using backend/.venv/bin/python. Default action is read-only.
Tokens are legitimate browser sessions in ignored .local/deep-validation/sessions.json.
No passwords, tokens or connection details are emitted in the report.
"""
import argparse
import ast
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.local/deep-validation'
API = 'http://127.0.0.1:18094/api/v1'


def read_json(path):
    return json.loads(path.read_text())


def session_token(sessions, name):
    value = sessions.get(name)
    if isinstance(value, str):
        return value
    return (value or {}).get('access_token') or (value or {}).get('token')


def http(method, path, token=None, body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(API + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    started = time.monotonic()
    try:
        response = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    try:
        raw = response.read()
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = None
        return response.status, data, round((time.monotonic() - started) * 1000, 1)
    finally:
        response.close()


def source_inventory():
    """AST inventory of physical routers selected by Platform's ModuleDefinition."""
    platform = ROOT / 'backend/app/modules/platform.py'
    tree = ast.parse(platform.read_text())
    modules = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in ('app.api.routes', 'app.platform.infra'):
            for alias in node.names:
                modules[alias.asname or alias.name] = node.module + '.' + alias.name
    inventory = []
    for alias, module in sorted(modules.items()):
        path = ROOT / 'backend' / (module.replace('.', '/') + '.py')
        if not path.exists():
            continue
        source = ast.parse(path.read_text())
        prefix = ''
        for node in source.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if any(isinstance(target, ast.Name) and target.id == 'router' for target in node.targets):
                    for kw in node.value.keywords:
                        if kw.arg == 'prefix' and isinstance(kw.value, ast.Constant):
                            prefix = kw.value.value
        for node in ast.walk(source):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != 'router':
                    continue
                method = decorator.func.attr.upper()
                if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE') or not decorator.args:
                    continue
                if isinstance(decorator.args[0], ast.Constant):
                    inventory.append({'method': method, 'path': prefix + decorator.args[0].value,
                                      'source': str(path.relative_to(ROOT)), 'line': node.lineno,
                                      'handler': node.name, 'router': alias})
    return inventory


def dotenv(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def sql_snapshot():
    # Direct SQL oracle uses only a SELECT-capable/DML runtime identity, never admin.
    import pymysql
    config = read_json(ROOT / '.local/test-services.json')
    env = dotenv(ROOT / '.env')
    database = env['MYSQL_DB']
    if not database.startswith('esop_fva_test_'):
        raise RuntimeError('Read-only oracle restricted to dedicated test schema')
    connection = pymysql.connect(host=env['MYSQL_SERVER'], port=int(env.get('MYSQL_PORT', '3306')),
                                 user=config['runtime_user'], password=config['runtime_password'],
                                 database=database, charset='utf8mb4', autocommit=False,
                                 cursorclass=pymysql.cursors.DictCursor)
    queries = {
        'foreign_tenant_role_bindings': 'SELECT COUNT(*) AS count FROM userrole ur JOIN role r ON r.id=ur.role_id WHERE ur.tenant_id<>r.tenant_id',
        'session_without_membership': 'SELECT COUNT(*) AS count FROM usersession s LEFT JOIN tenantmembership tm ON tm.user_id=s.user_id AND tm.tenant_id=s.tenant_id WHERE tm.user_id IS NULL',
        'tenants_without_plan': 'SELECT COUNT(*) AS count FROM tenant t LEFT JOIN tenantplan p ON p.id=t.plan_id WHERE p.id IS NULL',
        'tenants_without_template': 'SELECT COUNT(*) AS count FROM tenant t LEFT JOIN tenantinitializationtemplate x ON x.id=t.initialization_template_id WHERE x.id IS NULL',
        'active_default_plans': 'SELECT COUNT(*) AS count FROM tenantplan WHERE is_default=1 AND is_active=1',
        'active_default_templates': 'SELECT COUNT(*) AS count FROM tenantinitializationtemplate WHERE is_default=1 AND is_active=1',
        'plan_platform_menu_bindings': "SELECT COUNT(*) AS count FROM tenantplanmenu pm JOIN menu m ON m.id=pm.menu_id WHERE m.permission_code LIKE 'platform:%'",
        'cross_tenant_dictionary_items': 'SELECT COUNT(*) AS count FROM dictionaryitem i JOIN dictionarytype t ON t.id=i.type_id WHERE i.tenant_id<>t.tenant_id',
        'tables': 'SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name',
        'tenant_state': 'SELECT t.id AS id,t.is_active,t.plan_id AS plan_id,p.lifecycle_status,p.service_expires_at FROM tenant t LEFT JOIN tenantprofile p ON p.tenant_id=t.id ORDER BY t.id',
        'protected_test_identity': "SELECT u.id,u.username,u.is_active,u.is_superuser,tm.tenant_id,tm.is_active membership_active,tm.department_id FROM user u JOIN tenantmembership tm ON tm.user_id=u.id JOIN tenant t ON t.id=tm.tenant_id WHERE t.code='test' AND u.username='tangyun' ORDER BY u.id",
        'protected_test_role_bindings': "SELECT ur.user_id,ur.tenant_id,ur.role_id,r.is_active,rm.menu_id FROM userrole ur JOIN user u ON u.id=ur.user_id JOIN tenant t ON t.id=ur.tenant_id JOIN role r ON r.id=ur.role_id LEFT JOIN rolemenu rm ON rm.role_id=r.id WHERE t.code='test' AND u.username='tangyun' ORDER BY ur.role_id,rm.menu_id",
        'counts': 'SELECT (SELECT COUNT(*) FROM tenant) tenants,(SELECT COUNT(*) FROM user) users,(SELECT COUNT(*) FROM role) roles,(SELECT COUNT(*) FROM menu) menus,(SELECT COUNT(*) FROM fileasset) files,(SELECT COUNT(*) FROM operationlog) audit_rows',
    }
    try:
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            result = {}
            for name, query in queries.items():
                cursor.execute(query)
                result[name] = cursor.fetchall()
            connection.rollback()
            return result
    finally:
        connection.close()


def readonly_stage():
    sessions_path = OUT / 'sessions.json'
    sessions = read_json(sessions_path) if sessions_path.exists() else {}
    root = session_token(sessions, 'root')
    tenant = session_token(sessions, 'test')
    checks = []
    coverage = set()

    def check(label, method, path, token, allowed):
        status, data, duration = http(method, path, token)
        checks.append({'case': label, 'method': method, 'path': path, 'status': status,
                       'expected_status': allowed, 'pass': status in allowed, 'duration_ms': duration})
        coverage.add((method, path.split('?')[0]))
        return data if status == 200 else None

    check('unauthenticated protected resource', 'GET', '/users/me', None, [401, 403])
    check('malformed bearer rejected', 'GET', '/users/me', 'invalid', [401, 403])
    management = ['/users', '/roles', '/menus', '/tenants', '/tenants/plans', '/tenants/templates',
                  '/dictionary-types', '/dictionary-items', '/departments', '/posts', '/settings',
                  '/notices', '/site-messages/templates', '/site-messages/messages']
    if root:
        me = check('root identity', 'GET', '/users/me', root, [200])
        checks.append({'case': 'root boolean authority independently observed',
                       'pass': bool(me and me.get('is_superuser')), 'expected': True})
        for path in management:
            check('root can query Base management', 'GET', path, root, [200])
        check('root runtime navigation', 'GET', '/menus/me', root, [200])
    if tenant:
        me = check('requested tenant identity', 'GET', '/users/me', tenant, [200])
        checks.append({'case': 'requested tenant is not root despite role name',
                       'pass': bool(me and me.get('is_superuser') is False), 'expected': False})
        for path in ['/tenants', '/tenants/plans', '/tenants/templates', '/menus', '/dictionary-types', '/settings']:
            check('tenant cannot query platform management', 'GET', path, tenant, [403])
        check('tenant runtime navigation', 'GET', '/menus/me', tenant, [200])
        check('tenant effective permission catalog', 'GET', '/menus/permissions/me', tenant, [200])
    status, schema, _ = http('GET', '/openapi.json')
    if status != 200:
        raise RuntimeError('Public OpenAPI unavailable')
    live = {(method.upper(), path.removeprefix('/api/v1'))
            for path, methods in schema['paths'].items() for method in methods
            if method.upper() in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')}
    optional_paths = [path for _, path in live if path.startswith(('/items', '/erp', '/platform/items', '/platform/erp'))]
    checks.append({'case': 'optional Items ERP not exposed in Base OpenAPI', 'pass': not optional_paths,
                   'unexpected_paths': optional_paths})
    inventory = source_inventory()
    for item in inventory:
        key = item['method'], item['path']
        item['live_openapi'] = key in live or (item['method'], '/platform' + item['path']) in live
        item['exercised_in_readonly_stage'] = key in coverage
    snapshot = sql_snapshot()
    for name in ('foreign_tenant_role_bindings', 'session_without_membership', 'tenants_without_plan',
                 'tenants_without_template', 'cross_tenant_dictionary_items', 'plan_platform_menu_bindings'):
        count = snapshot[name][0]['count']
        checks.append({'case': 'SQL oracle ' + name, 'observed_count': count, 'pass': count == 0})
    for name in ('active_default_plans', 'active_default_templates'):
        count = snapshot[name][0]['count']
        checks.append({'case': 'SQL oracle ' + name, 'observed_count': count, 'pass': count == 1})
    OUT.mkdir(parents=True, exist_ok=True)
    protected = {key: snapshot[key] for key in ('protected_test_identity', 'protected_test_role_bindings')}
    fingerprint = hashlib.sha256(json.dumps(protected, sort_keys=True).encode()).hexdigest()
    baseline = OUT / 'protected-test-baseline.json'
    if not baseline.exists():
        baseline.write_text(json.dumps({'fingerprint': fingerprint, 'state': protected}, indent=2))
        baseline.chmod(0o600)
    checks.append({'case': 'protected test/tangyun identity and roles unchanged since oracle baseline',
                   'pass': fingerprint == read_json(baseline)['fingerprint']})
    evidence = {'timestamp': datetime.now(timezone.utc).isoformat(), 'stage': 'read-only',
                'token_roles_available': [name for name in ('root', 'test', 'a', 'b') if session_token(sessions, name)],
                'checks': checks, 'source_route_inventory': inventory, 'sql_snapshot': snapshot,
                'coverage': {'source_operations': len(inventory), 'http_operations_exercised': len(coverage),
                             'not_claimed': 'Unexecuted writes, external providers, browser UI, full-stack certification'}}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'readonly-evidence.json'
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    path.chmod(0o600)
    failed = [check['case'] for check in checks if not check['pass']]
    print(json.dumps({'stage': 'read-only', 'checks': len(checks), 'failed': failed,
                      'source_operations': len(inventory), 'http_operations_exercised': len(coverage),
                      'evidence': str(path.relative_to(ROOT))}, ensure_ascii=False))
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['readonly'], default='readonly')
    args = parser.parse_args()
    if args.stage == 'readonly':
        return readonly_stage()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
