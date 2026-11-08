"""Review queue filtering and role permission guards without a substitute DB."""
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import mysql

from app.api import deps
from app.modules.esop import product_sop_routes as routes


@pytest.mark.parametrize('path', ['/product-sop-versions', '/product-sop-versions/{id}/approve', '/product-sop-versions/{id}/reject'])
@pytest.mark.parametrize('allowed', [False, True])
def test_review_routes_require_role_permission(monkeypatch, path, allowed):
    route = next(route for route in routes.router.routes if route.path.endswith(path))
    guard = route.dependencies[0].dependency
    monkeypatch.setattr(deps, 'evaluate_module_access', lambda **kwargs: SimpleNamespace(allowed=True))
    permission = Mock(return_value=allowed)
    monkeypatch.setattr(deps, 'user_has_permission', permission)
    user, tenant_id = Mock(), uuid.uuid4()
    if allowed:
        assert guard(Mock(), user, SimpleNamespace(tenant_id=tenant_id)) is user
    else:
        with pytest.raises(HTTPException) as error:
            guard(Mock(), user, SimpleNamespace(tenant_id=tenant_id))
        assert error.value.status_code == 403
    assert permission.call_args.kwargs['permission_code'] == 'esop:sop:review'
    assert permission.call_args.kwargs['tenant_id'] == tenant_id


@pytest.mark.parametrize('status, expected', [('pending', "status = 'pending'"), ('reviewed', "status IN ('approved', 'rejected')")])
def test_review_tabs_filter_before_pagination(status, expected):
    session = Mock()
    session.exec.return_value.all.return_value = []
    result = routes.list_sop_review_versions(SimpleNamespace(session=session), status=status, page=2, page_size=20)
    sql = str(session.exec.call_args.args[0].compile(dialect=mysql.dialect(), compile_kwargs={'literal_binds': True}))
    assert expected in sql
    assert ('reviewed_at DESC' if status == 'reviewed' else 'submitted_at DESC') in sql
    assert result.total == 0 and result.items == []
