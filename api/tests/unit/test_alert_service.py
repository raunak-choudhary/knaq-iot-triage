"""Unit tests for AlertService business logic."""
import pytest

from app.exceptions import NotFoundError, TransitionError
from app.schemas.alert import AssignRequest, DismissRequest, NoteRequest, ResolveRequest
from app.services.alert_service import AlertService
from tests.factories.alert_factory import make_alert
from tests.factories.device_factory import make_device
from tests.factories.user_factory import make_user


@pytest.fixture
def brookfield_device(db):
    return make_device(db, device_id="BF-001", company="Brookfield Properties")


@pytest.fixture
def alice(db):
    return make_user(
        db, name="Alice Chen", role="Building Manager",
        company="Brookfield Properties", token="token-alice-bf-test"
    )


@pytest.fixture
def bob(db):
    return make_user(
        db, name="Bob Martinez", role="Technician",
        company="Brookfield Properties", token="token-bob-bf-test"
    )


@pytest.fixture
def hines_user(db):
    return make_user(
        db, name="Carol Kim", role="Building Manager",
        company="Hines", token="token-carol-hines-test"
    )


# --- acknowledge ---

def test_acknowledge_new_alert(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    result = svc.acknowledge(alert.id)
    assert result.status == "acknowledged"
    assert result.acknowledged_at is not None
    actions = [t.action for t in result.timeline]
    assert "acknowledged" in actions


def test_acknowledge_already_acknowledged_raises_409(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="acknowledged")
    svc = AlertService(db, alice)
    with pytest.raises(TransitionError) as exc_info:
        svc.acknowledge(alert.id)
    assert exc_info.value.status_code == 409
    assert "acknowledged" in exc_info.value.detail


def test_acknowledge_resolved_raises_409(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="resolved")
    svc = AlertService(db, alice)
    with pytest.raises(TransitionError) as exc_info:
        svc.acknowledge(alert.id)
    assert exc_info.value.status_code == 409
    assert "resolved" in exc_info.value.detail


# --- assign ---

def test_assign_on_new_alert(db, brookfield_device, alice, bob):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    result = svc.assign(alert.id, AssignRequest(assignee_id=bob.id))
    assert result.assigned_to == bob.id
    assert result.assignee_name == bob.name
    actions = [t.action for t in result.timeline]
    assert "assigned" in actions


def test_assign_on_acknowledged_alert(db, brookfield_device, alice, bob):
    alert = make_alert(db, device_id="BF-001", status="acknowledged")
    svc = AlertService(db, alice)
    result = svc.assign(alert.id, AssignRequest(assignee_id=bob.id))
    assert result.assigned_to == bob.id


def test_assign_on_resolved_raises_409(db, brookfield_device, alice, bob):
    alert = make_alert(db, device_id="BF-001", status="resolved")
    svc = AlertService(db, alice)
    with pytest.raises(TransitionError) as exc_info:
        svc.assign(alert.id, AssignRequest(assignee_id=bob.id))
    assert exc_info.value.status_code == 409


def test_assign_unknown_assignee_raises_404(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    with pytest.raises(NotFoundError) as exc_info:
        svc.assign(alert.id, AssignRequest(assignee_id="nonexistent-id"))
    assert exc_info.value.status_code == 404


def test_assign_cross_company_raises_404(db, brookfield_device, alice, hines_user):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    with pytest.raises(NotFoundError) as exc_info:
        svc.assign(alert.id, AssignRequest(assignee_id=hines_user.id))
    assert exc_info.value.status_code == 404


# --- resolve ---

def test_resolve_acknowledged_alert(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="acknowledged")
    svc = AlertService(db, alice)
    data = ResolveRequest(
        resolution_type="maintenance",
        root_cause="worn bearings",
        action_taken="replaced bearings",
        preventive_measures="schedule quarterly maintenance",
        time_spent_minutes=90,
    )
    result = svc.resolve(alert.id, data)
    assert result.status == "resolved"
    assert result.resolved_at is not None
    assert result.resolution_type == "maintenance"
    assert result.resolution_root_cause == "worn bearings"
    assert result.resolution_action_taken == "replaced bearings"
    actions = [t.action for t in result.timeline]
    assert "resolved" in actions


def test_resolve_new_raises_409(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    with pytest.raises(TransitionError) as exc_info:
        svc.resolve(alert.id, ResolveRequest(
            resolution_type="maintenance",
            root_cause="cause",
            action_taken="action",
        ))
    assert exc_info.value.status_code == 409
    assert "new" in exc_info.value.detail


def test_resolve_already_resolved_raises_409(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="resolved")
    svc = AlertService(db, alice)
    with pytest.raises(TransitionError) as exc_info:
        svc.resolve(alert.id, ResolveRequest(
            resolution_type="maintenance",
            root_cause="cause",
            action_taken="action",
        ))
    assert exc_info.value.status_code == 409


# --- add_note ---

def test_add_note_on_new_alert(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    result = svc.add_note(alert.id, NoteRequest(note="Investigating now"))
    assert result.status == "new"  # no status change
    notes = [t for t in result.timeline if t.action == "note"]
    assert len(notes) == 1
    assert notes[0].note == "Investigating now"


def test_add_note_on_resolved_alert(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="resolved")
    svc = AlertService(db, alice)
    result = svc.add_note(alert.id, NoteRequest(note="Post-resolution note"))
    assert result.status == "resolved"  # still resolved
    notes = [t for t in result.timeline if t.action == "note"]
    assert len(notes) == 1


# --- timeline ordering ---

def test_timeline_ordering(db, brookfield_device, alice, bob):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    svc.acknowledge(alert.id)
    svc.assign(alert.id, AssignRequest(assignee_id=bob.id))
    result = svc.add_note(alert.id, NoteRequest(note="test note"))
    timestamps = [t.timestamp for t in result.timeline]
    assert timestamps == sorted(timestamps)


# --- cross-company 404 ---

def test_get_alert_cross_company_returns_404(db, brookfield_device, alice, hines_user):
    alert = make_alert(db, device_id="BF-001", status="new")
    # Hines user tries to access Brookfield alert
    make_device(db, device_id="HN-001", company="Hines")
    svc = AlertService(db, hines_user)
    with pytest.raises(NotFoundError):
        svc.acknowledge(alert.id)


# --- dismiss and reopen ---

def test_dismiss_new_alert(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="new")
    svc = AlertService(db, alice)
    result = svc.dismiss(alert.id, DismissRequest(note="Not actionable"))
    assert result.status == "dismissed"


def test_reopen_resolved_alert(db, brookfield_device, alice):
    alert = make_alert(db, device_id="BF-001", status="resolved")
    svc = AlertService(db, alice)
    result = svc.reopen(alert.id)
    assert result.status == "acknowledged"
