"""Integration tests for alert mutation endpoints."""
import pytest

from tests.conftest import auth_headers
from tests.factories.alert_factory import make_alert


@pytest.fixture
def setup(db, seeded_users, seeded_devices):
    return seeded_users


def _get_user_id(client, token):
    response = client.get("/users", headers=auth_headers(token))
    users = response.json()
    return users[0]["id"]


def test_full_workflow_new_ack_assign_note_resolve(client, db, seeded_users, seeded_devices):
    """Full workflow: new→acknowledge→assign→note→resolve = timeline 5 entries."""
    alert = make_alert(db, device_id="ELV-001", status="new")

    # 1. acknowledge
    r = client.post(f"/alerts/{alert.id}/acknowledge", headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    assert r.json()["status"] == "acknowledged"

    # 2. assign (to bob)
    bob_id = seeded_users["token-bob-brookfield"].id
    r = client.post(f"/alerts/{alert.id}/assign",
                    json={"assignee_id": bob_id, "note": "Please handle"},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    assert r.json()["assigned_to"] == bob_id

    # 3. add note
    r = client.post(f"/alerts/{alert.id}/notes",
                    json={"note": "Inspecting motor"},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200

    # 4. resolve
    r = client.post(f"/alerts/{alert.id}/resolve",
                    json={
                        "resolution_type": "maintenance",
                        "root_cause": "worn motor",
                        "action_taken": "replaced motor",
                        "preventive_measures": "quarterly check",
                        "time_spent_minutes": 120,
                    },
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "resolved"

    # 5 entries: created, acknowledged, assigned, note, resolved
    assert len(data["timeline"]) == 5
    actions = [t["action"] for t in data["timeline"]]
    assert "created" in actions
    assert "acknowledged" in actions
    assert "assigned" in actions
    assert "note" in actions
    assert "resolved" in actions


def test_acknowledge_already_acknowledged_returns_409(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="acknowledged")
    r = client.post(f"/alerts/{alert.id}/acknowledge", headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 409
    assert "acknowledged" in r.json()["detail"]


def test_acknowledge_cross_company_returns_404(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="new")
    r = client.post(f"/alerts/{alert.id}/acknowledge", headers=auth_headers("token-carol-hines"))
    assert r.status_code == 404


def test_resolve_new_alert_returns_409(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="new")
    r = client.post(f"/alerts/{alert.id}/resolve",
                    json={"resolution_type": "x", "root_cause": "y", "action_taken": "z"},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 409


def test_resolve_acknowledged_alert_ok(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="acknowledged")
    r = client.post(f"/alerts/{alert.id}/resolve",
                    json={"resolution_type": "x", "root_cause": "y", "action_taken": "z"},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"


def test_resolve_missing_required_field_returns_422(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="acknowledged")
    # missing root_cause and action_taken
    r = client.post(f"/alerts/{alert.id}/resolve",
                    json={"resolution_type": "maintenance"},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 422


def test_assign_new_alert_ok(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="new")
    bob_id = seeded_users["token-bob-brookfield"].id
    r = client.post(f"/alerts/{alert.id}/assign",
                    json={"assignee_id": bob_id},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    assert r.json()["assigned_to"] == bob_id


def test_assign_resolved_alert_returns_409(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="resolved")
    bob_id = seeded_users["token-bob-brookfield"].id
    r = client.post(f"/alerts/{alert.id}/assign",
                    json={"assignee_id": bob_id},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 409


def test_assign_unknown_assignee_returns_404(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="new")
    r = client.post(f"/alerts/{alert.id}/assign",
                    json={"assignee_id": "nonexistent-user-id"},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 404


def test_assign_cross_company_assignee_returns_404(client, db, seeded_users, seeded_devices):
    """Hines user cannot be assigned to Brookfield alert."""
    alert = make_alert(db, device_id="ELV-001", status="new")
    carol_id = seeded_users["token-carol-hines"].id
    r = client.post(f"/alerts/{alert.id}/assign",
                    json={"assignee_id": carol_id},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 404


def test_add_note_any_status(client, db, seeded_users, seeded_devices):
    for status in ["new", "acknowledged", "resolved"]:
        alert = make_alert(db, device_id="ELV-001", status=status)
        r = client.post(f"/alerts/{alert.id}/notes",
                        json={"note": f"Note on {status}"},
                        headers=auth_headers("token-alice-brookfield"))
        assert r.status_code == 200
        data = r.json()
        notes = [t for t in data["timeline"] if t["action"] == "note"]
        assert len(notes) == 1


def test_get_resolved_alert_has_complete_data(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="acknowledged")
    client.post(f"/alerts/{alert.id}/resolve",
                json={"resolution_type": "maintenance", "root_cause": "cause",
                      "action_taken": "action taken"},
                headers=auth_headers("token-alice-brookfield"))
    r = client.get(f"/alerts/{alert.id}", headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "resolved"
    assert data["resolution_type"] == "maintenance"


def test_dismiss_alert(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="new")
    r = client.post(f"/alerts/{alert.id}/dismiss",
                    json={"note": "Not relevant"},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"


def test_dismiss_resolved_returns_409(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="resolved")
    r = client.post(f"/alerts/{alert.id}/dismiss",
                    json={},
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 409


def test_reopen_resolved_alert(client, db, seeded_users, seeded_devices):
    alert = make_alert(db, device_id="ELV-001", status="resolved")
    r = client.post(f"/alerts/{alert.id}/reopen",
                    headers=auth_headers("token-alice-brookfield"))
    assert r.status_code == 200
    assert r.json()["status"] == "acknowledged"
