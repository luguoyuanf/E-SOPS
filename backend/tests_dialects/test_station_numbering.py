"""Numbering changes rearrange geometry, never station/device/plan identity."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.modules.esop.infrastructure.models import ProductionLine, Station
from app.modules.esop.production_routes import (
    _apply_stations,
    _station_position,
    update_line,
)
from app.modules.esop.public_api.production_dto import LineInput


@pytest.mark.parametrize("count", [1, 2, 11, 20, 200])
def test_numbering_modes(count):
    for mode in ("sequential", "odd_even"):
        coordinates = [_station_position("double", p, count, mode) for p in range(1, count + 1)]
        assert len(set(coordinates)) == count
        assert all(1 <= row <= 2 and 1 <= col <= (count + 1) // 2 for row, col in coordinates)
        first = [p for p, (row, _) in enumerate(coordinates, 1) if row == 1]
        assert first == (list(range(1, (count + 1) // 2 + 1)) if mode == "sequential" else list(range(1, count + 1, 2)))
    assert _station_position("single", count, count, "sequential") == (1, count)


def test_names_and_layout_preserve_station_identity():
    tenant, line_id = uuid.uuid4(), uuid.uuid4()
    stations = [Station(tenant_id=tenant, line_id=line_id, position=p, row=(p % 2 or 2), column=(p + 1) // 2, name="原名") for p in range(1, 5)]
    ids = [s.id for s in stations]
    line = ProductionLine(id=line_id, tenant_id=tenant, workshop_id=uuid.uuid4(), code="L", name="线", layout="double", station_count=4, numbering_mode="sequential")
    uow = SimpleNamespace(session=MagicMock(), tenant_id=tenant)
    with patch('app.modules.esop.production_routes._stations', return_value=stations):
        _apply_stations(uow, line, {1: "  装配  ", 2: ""})
    assert [s.id for s in stations] == ids
    assert [(s.row, s.column) for s in stations] == [(1, 1), (1, 2), (2, 1), (2, 2)]
    assert [s.name for s in stations] == ["装配", "", "原名", "原名"]
    uow.session.delete.assert_not_called()


def test_numbering_and_names_can_change_without_rewriting_plan_assignments():
    tenant = uuid.uuid4()
    line = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code="L", name="线", layout="double", station_count=4)
    body = LineInput(workshop_id=line.workshop_id, name="线", layout="double", station_count=4, numbering_mode="sequential", station_names={1: "上料"})
    uow = SimpleNamespace(session=MagicMock(), tenant_id=tenant)
    with patch('app.modules.esop.production_routes._owned', side_effect=[object(), line]), patch('app.modules.esop.production_routes._apply_stations') as apply, patch('app.modules.esop.production_routes._line_public'):
        update_line(uow, line.id, body)
    apply.assert_called_once_with(uow, line, {1: "上料"})
    assert line.numbering_mode == "sequential"
    uow.session.exec.assert_not_called()


def test_legacy_request_keeps_saved_numbering_and_names():
    tenant = uuid.uuid4()
    line = ProductionLine(tenant_id=tenant, workshop_id=uuid.uuid4(), code="L", name="线", layout="double", station_count=4, numbering_mode="sequential")
    body = LineInput(workshop_id=line.workshop_id, name="新线名", layout="double", station_count=4)
    uow = SimpleNamespace(session=MagicMock(), tenant_id=tenant)
    with patch('app.modules.esop.production_routes._owned', side_effect=[object(), line]), patch('app.modules.esop.production_routes._apply_stations') as apply, patch('app.modules.esop.production_routes._line_public'):
        update_line(uow, line.id, body)
    assert line.numbering_mode == "sequential"
    apply.assert_not_called()


@pytest.mark.parametrize('extra', [{"numbering_mode": "bad"}, {"station_names": {3: "越界"}}, {"station_names": {0: "越界"}}, {"station_names": {1: "名" * 101}}])
def test_invalid_station_configuration(extra):
    with pytest.raises(ValidationError):
        LineInput(workshop_id=uuid.uuid4(), name="线", layout="double", station_count=2, **extra)
