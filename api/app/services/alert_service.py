import time

import structlog
from sqlalchemy.orm import Session

from app.exceptions import NotFoundError, TransitionError
from app.models.alert import Alert
from app.models.alert_timeline import AlertTimeline
from app.models.device import Device
from app.models.user import User
from app.repositories.alert_repository import AlertRepository
from app.repositories.user_repository import UserRepository
from app.schemas.alert import (
    AlertResponse,
    AssignRequest,
    DismissRequest,
    NoteRequest,
    ResolveRequest,
    TimelineEntry,
)

logger = structlog.get_logger()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _build_alert_response(
    alert: Alert, device: Device, assignee: User | None, timeline: list[AlertTimeline]
) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        device_id=alert.device_id,
        device_name=device.name,
        device_location=device.location,
        alert_type=alert.alert_type,
        severity=alert.severity,
        title=alert.title,
        status=alert.status,
        timestamp_utc=alert.timestamp_utc,
        timestamp_local=alert.timestamp_local,
        assigned_to=alert.assigned_to,
        assignee_name=assignee.name if assignee else None,
        reading_value=alert.reading_value,
        threshold=alert.threshold,
        reading_name=alert.reading_name,
        acknowledged_at=alert.acknowledged_at,
        resolved_at=alert.resolved_at,
        resolution_type=alert.resolution_type,
        resolution_root_cause=alert.resolution_root_cause,
        resolution_action_taken=alert.resolution_action_taken,
        resolution_preventive_measures=alert.resolution_preventive_measures,
        resolution_time_spent_minutes=alert.resolution_time_spent_minutes,
        timeline=[
            TimelineEntry(
                id=t.id,
                timestamp=t.timestamp,
                action=t.action,
                user_name=t.user_name,
                details=t.details,
                note=t.note,
            )
            for t in timeline
        ],
    )


class AlertService:
    def __init__(self, db: Session, current_user: User):
        self.db = db
        self.current_user = current_user
        self.alert_repo = AlertRepository(db)
        self.user_repo = UserRepository(db)

    def _enforce_transition(self, alert: Alert, allowed_statuses: list[str], action_name: str) -> None:
        if alert.status not in allowed_statuses:
            raise TransitionError(
                detail=f"Cannot {action_name} an alert with status '{alert.status}'."
            )

    def _fetch_alert(self, alert_id: str) -> tuple[Alert, Device, User | None]:
        result = self.alert_repo.get_by_id_and_company(alert_id, self.current_user.company)
        if result is None:
            raise NotFoundError(detail=f"Alert '{alert_id}' not found.")
        alert, device, assignee = result
        return alert, device, assignee

    def _get_full_response(self, alert: Alert, device: Device, assignee: User | None) -> AlertResponse:
        timeline = self.alert_repo.get_timeline(alert.id)
        return _build_alert_response(alert, device, assignee, timeline)

    def _get_assignee(self, alert: Alert) -> User | None:
        if alert.assigned_to:
            return self.db.get(User, alert.assigned_to)
        return None

    def acknowledge(self, alert_id: str) -> AlertResponse:
        alert, device, assignee = self._fetch_alert(alert_id)
        self._enforce_transition(alert, ["new"], "acknowledge")
        now = _now_ms()
        alert.status = "acknowledged"
        alert.acknowledged_at = now
        timeline = AlertTimeline(
            alert_id=alert.id,
            timestamp=now,
            action="acknowledged",
            user_name=self.current_user.name,
            details=None,
            note=None,
        )
        self.db.add(timeline)
        self.db.commit()
        self.db.refresh(alert)
        return self._get_full_response(alert, device, assignee)

    def assign(self, alert_id: str, data: AssignRequest) -> AlertResponse:
        alert, device, current_assignee = self._fetch_alert(alert_id)
        self._enforce_transition(alert, ["new", "acknowledged"], "assign")

        assignee = self.user_repo.get_by_id_and_company(data.assignee_id, self.current_user.company)
        if assignee is None:
            raise NotFoundError(detail=f"User '{data.assignee_id}' not found in your company.")

        alert.assigned_to = assignee.id
        now = _now_ms()
        timeline = AlertTimeline(
            alert_id=alert.id,
            timestamp=now,
            action="assigned",
            user_name=self.current_user.name,
            details=f"Assigned to {assignee.name}",
            note=data.note,
        )
        self.db.add(timeline)
        self.db.commit()
        self.db.refresh(alert)
        return self._get_full_response(alert, device, assignee)

    def resolve(self, alert_id: str, data: ResolveRequest) -> AlertResponse:
        alert, device, assignee = self._fetch_alert(alert_id)
        self._enforce_transition(alert, ["acknowledged"], "resolve")
        now = _now_ms()
        alert.status = "resolved"
        alert.resolved_at = now
        alert.resolution_type = data.resolution_type
        alert.resolution_root_cause = data.root_cause
        alert.resolution_action_taken = data.action_taken
        alert.resolution_preventive_measures = data.preventive_measures
        alert.resolution_time_spent_minutes = data.time_spent_minutes
        timeline = AlertTimeline(
            alert_id=alert.id,
            timestamp=now,
            action="resolved",
            user_name=self.current_user.name,
            details=f"Resolved: {data.resolution_type}",
            note=None,
        )
        self.db.add(timeline)
        self.db.commit()
        self.db.refresh(alert)
        updated_assignee = self._get_assignee(alert)
        return self._get_full_response(alert, device, updated_assignee)

    def add_note(self, alert_id: str, data: NoteRequest) -> AlertResponse:
        alert, device, assignee = self._fetch_alert(alert_id)
        now = _now_ms()
        timeline = AlertTimeline(
            alert_id=alert.id,
            timestamp=now,
            action="note",
            user_name=self.current_user.name,
            details=None,
            note=data.note,
        )
        self.db.add(timeline)
        self.db.commit()
        self.db.refresh(alert)
        updated_assignee = self._get_assignee(alert)
        return self._get_full_response(alert, device, updated_assignee)

    def dismiss(self, alert_id: str, data: DismissRequest | None = None) -> AlertResponse:
        alert, device, assignee = self._fetch_alert(alert_id)
        self._enforce_transition(alert, ["new", "acknowledged"], "dismiss")
        now = _now_ms()
        alert.status = "dismissed"
        note_text = data.note if data else None
        timeline = AlertTimeline(
            alert_id=alert.id,
            timestamp=now,
            action="dismissed",
            user_name=self.current_user.name,
            details=None,
            note=note_text,
        )
        self.db.add(timeline)
        self.db.commit()
        self.db.refresh(alert)
        updated_assignee = self._get_assignee(alert)
        return self._get_full_response(alert, device, updated_assignee)

    def reopen(self, alert_id: str) -> AlertResponse:
        alert, device, assignee = self._fetch_alert(alert_id)
        self._enforce_transition(alert, ["resolved", "dismissed"], "reopen")
        now = _now_ms()
        alert.status = "acknowledged"
        timeline = AlertTimeline(
            alert_id=alert.id,
            timestamp=now,
            action="reopened",
            user_name=self.current_user.name,
            details=None,
            note=None,
        )
        self.db.add(timeline)
        self.db.commit()
        self.db.refresh(alert)
        updated_assignee = self._get_assignee(alert)
        return self._get_full_response(alert, device, updated_assignee)
