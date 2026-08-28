"""Integration tests for alert read endpoints."""
import pytest

from tests.conftest import auth_headers
from tests.factories.alert_factory import make_alert

BROOKFIELD_DEVICES = ["ELV-001", "ELV-002", "ESC-002", "CMP-001"]
HINES_DEVICES = ["ELV-003", "ELV-004", "CMP-002", "CMP-004"]


@pytest.fixture
def setup_multi_company(db, seeded_users, seeded_devices):
    """Create alerts for all companies."""
    alerts = {}
    for device_id in BROOKFIELD_DEVICES:
        a = make_alert(db, device_id=device_id, severity="warning", status="new",
                       timestamp_utc=1750000000000 + hash(device_id) % 10000)
        alerts[device_id] = a

    for device_id in HINES_DEVICES:
        a = make_alert(db, device_id=device_id, severity="critical", status="new",
                       timestamp_utc=1750000000000 + hash(device_id) % 10000)
        alerts[device_id] = a

    # Mitsui
    make_alert(db, device_id="ESC-001", severity="info", status="new")
    make_alert(db, device_id="CMP-003", severity="info", status="new")
    return alerts


def test_brookfield_sees_only_own_alerts(client, setup_multi_company):
    response = client.get("/alerts", headers=auth_headers("token-alice-brookfield"))
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    device_ids = {a["device_id"] for a in payload["items"]}
    for did in device_ids:
        assert did in BROOKFIELD_DEVICES, f"Unexpected device_id: {did}"


def test_hines_sees_only_own_alerts(client, setup_multi_company):
    response = client.get("/alerts", headers=auth_headers("token-carol-hines"))
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    device_ids = {a["device_id"] for a in payload["items"]}
    for did in device_ids:
        assert did in HINES_DEVICES, f"Unexpected device_id: {did}"


def test_severity_filter(client, setup_multi_company):
    response = client.get("/alerts?severity=critical", headers=auth_headers("token-carol-hines"))
    assert response.status_code == 200
    payload = response.json()
    items = payload["items"]
    assert len(items) > 0
    for a in items:
        assert a["severity"] == "critical"


def test_multi_status_filter(client, db, seeded_users, seeded_devices):
    make_alert(db, device_id="ELV-001", status="new")
    make_alert(db, device_id="ELV-002", status="acknowledged")
    make_alert(db, device_id="ESC-002", status="resolved")

    response = client.get(
        "/alerts?status=new&status=acknowledged",
        headers=auth_headers("token-alice-brookfield")
    )
    assert response.status_code == 200
    payload = response.json()
    statuses = {a["status"] for a in payload["items"]}
    assert "resolved" not in statuses
    assert "new" in statuses or "acknowledged" in statuses


def test_q_search_by_title(client, db, seeded_users, seeded_devices):
    make_alert(db, device_id="ELV-001", alert_type="high_temperature",
               title="High Temperature on Main Lobby Elevator #1")
    response = client.get("/alerts?q=temperature", headers=auth_headers("token-alice-brookfield"))
    assert response.status_code == 200
    payload = response.json()
    assert any("temperature" in a["title"].lower() for a in payload["items"])


def test_get_alert_by_id_own_company(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001")
    response = client.get(f"/alerts/{alert.id}", headers=auth_headers("token-alice-brookfield"))
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == alert.id
    assert "timeline" in data


def test_get_alert_cross_company_returns_404(client, db, seeded_users, seeded_devices):
    # Brookfield alert, accessed with Hines token
    alert = make_alert(db, device_id="ELV-001")
    response = client.get(f"/alerts/{alert.id}", headers=auth_headers("token-carol-hines"))
    assert response.status_code == 404


def test_get_nonexistent_alert_returns_404(client, seeded_users, seeded_devices):
    response = client.get("/alerts/nonexistent-id", headers=auth_headers("token-alice-brookfield"))
    assert response.status_code == 404


def test_users_company_scoped(client, seeded_users, seeded_devices):
    response = client.get("/users", headers=auth_headers("token-alice-brookfield"))
    assert response.status_code == 200
    data = response.json()
    for user in data:
        assert user["company"] == "Brookfield Properties"
    # Should have 2 Brookfield users
    assert len(data) == 2
