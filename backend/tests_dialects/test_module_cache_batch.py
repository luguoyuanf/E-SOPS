from types import SimpleNamespace
from unittest.mock import Mock

from app.modules import access


def test_module_cache_reads_are_batched_and_missing_or_invalid_values_are_rechecked(
    monkeypatch,
):
    manifest = SimpleNamespace(
        manifest_digest="digest",
        modules=[SimpleNamespace(code="erp"), SimpleNamespace(code="esop")],
    )
    monkeypatch.setattr(access, "get_runtime_manifest", lambda: manifest)
    monkeypatch.setattr(
        access,
        "module_for_permission",
        lambda permission: permission.split(":")[0] if ":" in permission else None,
    )
    cache = SimpleNamespace(
        get_namespace_version=Mock(return_value=9),
        build_key=lambda *parts: ":".join(map(str, parts)),
        get_json_many=Mock(return_value=[{"allowed": True}, {"allowed": False}]),
    )
    monkeypatch.setattr(access, "redis_cache", cache)
    fallback = Mock(return_value=access.ModuleAccessDecision(True))
    monkeypatch.setattr(access, "evaluate_module_access", fallback)
    args = {
        "session": None,
        "tenant_id": "tenant",
        "permission_codes": ["erp:view", "erp:edit", "esop:view", "public"],
    }
    assert access.filter_module_scoped_permissions(**args) == [
        "erp:view",
        "erp:edit",
        "public",
    ]
    cache.get_namespace_version.assert_called_once()
    cache.get_json_many.assert_called_once()
    assert len(cache.get_json_many.call_args.args[0]) == 2
    fallback.assert_not_called()
    cache.get_json_many.return_value = [None, {"allowed": "invalid"}]
    assert access.filter_module_scoped_permissions(**args) == args["permission_codes"]
    assert fallback.call_count == 2
