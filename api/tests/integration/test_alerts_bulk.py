"""Integration tests for the bulk acknowledge and bulk assign endpoints."""
import pytest

from app.models.alert import Alert
from tests.conftest import auth_headers
from tests.factories.alert_factory import make_alert

ALICE = "token-alice-brookfield"


@pytest.fixture
def setup(db, seeded_users, seeded_devices):
    return seeded_users


def _status_of(db, alert_id):
    return db.query(Alert).filter(Alert.id == alert_id).one().status


# --- bulk acknowledge ---


def test_bulk_acknowledge_requires_authentication(client, setup):
    assert client.post("/alerts/bulk/acknowledge", json={"alert_ids": []}).status_code == 401


def test_bulk_acknowledge_moves_every_alert_to_acknowledged(client, db, setup):
    """The happy path acknowledges all supplied alerts and reports no failures."""
    alerts = [make_alert(db, device_id="ELV-001", status="new") for _ in range(3)]
    db.commit()
    ids = [a.id for a in alerts]

    response = client.post(
        "/alerts/bulk/acknowledge", json={"alert_ids": ids}, headers=auth_headers(ALICE)
    )

    assert response.status_code == 200
    assert response.json() == {"succeeded": 3, "failed": 0, "errors": []}
    assert all(_status_of(db, i) == "acknowledged" for i in ids)


def test_bulk_acknowledge_with_empty_list_is_a_no_op(client, setup):
    response = client.post(
        "/alerts/bulk/acknowledge", json={"alert_ids": []}, headers=auth_headers(ALICE)
    )
    assert response.json() == {"succeeded": 0, "failed": 0, "errors": []}


def test_bulk_acknowledge_reports_per_alert_failures_without_aborting(client, db, setup):
    """One bad id must not prevent the remaining alerts from being acknowledged."""
    good = make_alert(db, device_id="ELV-001", status="new")
    db.commit()

    response = client.post(
        "/alerts/bulk/acknowledge",
        json={"alert_ids": [good.id, "does-not-exist"]},
        headers=auth_headers(ALICE),
    )

    body = response.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["errors"][0]["id"] == "does-not-exist"
    assert _status_of(db, good.id) == "acknowledged"


def test_bulk_acknowledge_rejects_alerts_not_in_the_new_state(client, db, setup):
    """Already acknowledged alerts fail the transition guard instead of double counting."""
    already = make_alert(db, device_id="ELV-001", status="acknowledged")
    fresh = make_alert(db, device_id="ELV-002", status="new")
    db.commit()

    body = client.post(
        "/alerts/bulk/acknowledge",
        json={"alert_ids": [already.id, fresh.id]},
        headers=auth_headers(ALICE),
    ).json()

    assert body["succeeded"] == 1
    assert body["failed"] == 1


def test_bulk_acknowledge_cannot_reach_another_companys_alerts(client, db, setup):
    """Cross company ids fail and the foreign alert stays untouched."""
    mine = make_alert(db, device_id="ELV-001", status="new")   # Brookfield
    theirs = make_alert(db, device_id="ELV-003", status="new")  # Hines
    db.commit()

    body = client.post(
        "/alerts/bulk/acknowledge",
        json={"alert_ids": [mine.id, theirs.id]},
        headers=auth_headers(ALICE),
    ).json()

    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert _status_of(db, theirs.id) == "new"


# --- bulk assign ---


def test_bulk_assign_requires_authentication(client, setup):
    payload = {"alert_ids": [], "assignee_id": "x"}
    assert client.post("/alerts/bulk/assign", json=payload).status_code == 401


def test_bulk_assign_sets_the_assignee_on_every_alert(client, db, seeded_users, seeded_devices):
    alerts = [make_alert(db, device_id="ELV-001", status="new") for _ in range(3)]
    db.commit()
    ids = [a.id for a in alerts]
    bob_id = seeded_users["token-bob-brookfield"].id

    response = client.post(
        "/alerts/bulk/assign",
        json={"alert_ids": ids, "assignee_id": bob_id, "note": "Please review"},
        headers=auth_headers(ALICE),
    )

    assert response.status_code == 200
    assert response.json() == {"succeeded": 3, "failed": 0, "errors": []}
    rows = db.query(Alert).filter(Alert.id.in_(ids)).all()
    assert all(row.assigned_to == bob_id for row in rows)


def test_bulk_assign_accepts_acknowledged_alerts(client, db, seeded_users, seeded_devices):
    """Assignment is allowed from both new and acknowledged."""
    alert = make_alert(db, device_id="ELV-001", status="acknowledged")
    db.commit()
    bob_id = seeded_users["token-bob-brookfield"].id

    body = client.post(
        "/alerts/bulk/assign",
        json={"alert_ids": [alert.id], "assignee_id": bob_id},
        headers=auth_headers(ALICE),
    ).json()

    assert body["succeeded"] == 1


def test_bulk_assign_fails_every_alert_when_assignee_is_outside_the_company(
    client, db, seeded_users, seeded_devices
):
    """A Hines assignee is not resolvable for a Brookfield caller, so nothing is assigned."""
    alerts = [make_alert(db, device_id="ELV-001", status="new") for _ in range(2)]
    db.commit()
    ids = [a.id for a in alerts]
    carol_id = seeded_users["token-carol-hines"].id

    body = client.post(
        "/alerts/bulk/assign",
        json={"alert_ids": ids, "assignee_id": carol_id},
        headers=auth_headers(ALICE),
    ).json()

    assert body["succeeded"] == 0
    assert body["failed"] == 2
    rows = db.query(Alert).filter(Alert.id.in_(ids)).all()
    assert all(row.assigned_to is None for row in rows)


def test_bulk_assign_reports_partial_failures(client, db, seeded_users, seeded_devices):
    good = make_alert(db, device_id="ELV-001", status="new")
    db.commit()
    bob_id = seeded_users["token-bob-brookfield"].id

    body = client.post(
        "/alerts/bulk/assign",
        json={"alert_ids": [good.id, "does-not-exist"], "assignee_id": bob_id},
        headers=auth_headers(ALICE),
    ).json()

    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["errors"][0]["id"] == "does-not-exist"
