"""Deletion refuses every live/history reference, including cross-line JSON assignments."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.esop.infrastructure.models import ProductionLine, Station
from app.modules.esop.production_routes import delete_line


def fixture():
    tenant_id = uuid.uuid4()
    line = ProductionLine(
        tenant_id=tenant_id,
        workshop_id=uuid.uuid4(),
        code="L",
        name="线",
        station_count=2,
    )
    stations = [
        Station(tenant_id=tenant_id, line_id=line.id, position=i, row=1, column=i)
        for i in (1, 2)
    ]
    session = MagicMock()
    return SimpleNamespace(session=session, tenant_id=tenant_id), line, stations


def test_unused_line_deletes_only_own_stations():
    uow, line, stations = fixture()
    uow.session.exec.side_effect = [
        MagicMock(all=lambda: stations),
        MagicMock(all=lambda: []),
        MagicMock(all=lambda: []),
        *[MagicMock(first=lambda: None) for _ in range(3)],
    ]
    with patch("app.modules.esop.production_routes._owned", return_value=line):
        delete_line(uow, line.id)
    assert [call.args[0] for call in uow.session.delete.call_args_list] == [
        *stations,
        line,
    ]
    uow.session.commit.assert_called_once()


@pytest.mark.parametrize(
    "kind",
    [
        "plan",
        "cross_plan_station",
        "cross_plan_line",
        "release",
        "cross_release",
        "terminal",
        "report",
        "alarm",
    ],
)
def test_references_block_and_never_cascade(kind):
    uow, line, stations = fixture()
    plans, releases = [], []
    if kind == "plan":
        plans = [(line.id, [])]
    if kind == "cross_plan_station":
        plans = [(uuid.uuid4(), [{"station_id": str(stations[0].id)}])]
    if kind == "cross_plan_line":
        plans = [(uuid.uuid4(), [{"line_id": str(line.id)}])]
    if kind == "release":
        releases = [(line.id, [])]
    if kind == "cross_release":
        releases = [(uuid.uuid4(), [{"station_id": str(stations[0].id)}])]
    result = [
        MagicMock(all=lambda: stations),
        MagicMock(all=lambda: plans),
        MagicMock(all=lambda: releases),
    ]
    for ref in ["terminal", "report", "alarm"]:
        result.append(
            MagicMock(first=lambda match=ref: uuid.uuid4() if kind == match else None)
        )
    uow.session.exec.side_effect = result
    with (
        patch("app.modules.esop.production_routes._owned", return_value=line),
        pytest.raises(HTTPException) as error,
    ):
        delete_line(uow, line.id)
    assert error.value.status_code == 409
    assert (
        "请先解绑" in error.value.detail
        if kind == "terminal"
        else "无法删除" in error.value.detail
    )
    uow.session.delete.assert_not_called()
    uow.session.commit.assert_not_called()


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_foreign_line_404(missing):
    uow, line, _ = fixture()
    line.tenant_id = uuid.uuid4()
    uow.session.exec.return_value.first.return_value = None if missing else line
    with pytest.raises(HTTPException) as error:
        delete_line(uow, line.id)
    assert error.value.status_code == 404
    uow.session.delete.assert_not_called()
