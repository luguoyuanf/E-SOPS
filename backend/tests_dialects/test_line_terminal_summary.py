"""Line summaries use station identity for terminal bindings without listing devices."""
import uuid
from unittest.mock import Mock

from app.modules.esop.infrastructure.models import ProductionLine, Station, Terminal
from app.modules.esop.production_routes import _line_public


def test_line_summary_includes_bound_and_unbound_stations():
    tenant_id, line_id = uuid.uuid4(), uuid.uuid4()
    stations = [Station(tenant_id=tenant_id, line_id=line_id, position=i, row=1, column=i) for i in (1, 2)]
    uow = Mock()
    terminal = Terminal(tenant_id=tenant_id, device_code="TERMINAL-1", serial_number="SN00000001", station_id=stations[0].id)
    uow.session.exec.return_value.all.side_effect = [stations, [terminal]]
    result = _line_public(uow, ProductionLine(id=line_id, tenant_id=tenant_id, workshop_id=uuid.uuid4(), code="L", name="Line", layout="single", station_count=2))
    assert [(s.id, s.terminal_code) for s in result.stations] == [(stations[0].id, "SN00000001"), (stations[1].id, None)]
