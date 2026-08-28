import math
from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.exceptions import NotFoundError
from app.models.alert import Alert
from app.models.device import Device
from app.models.user import User
from app.repositories.alert_repository import AlertRepository
from app.schemas.alert import (
    AlertListItem,
    AlertResponse,
    AlertStatsResponse,
    AssignRequest,
    BulkAcknowledgeRequest,
    BulkAssignRequest,
    BulkOperationResult,
    DismissRequest,
    NoteRequest,
    PaginatedAlertsResponse,
    ResolveRequest,
    SeverityCounts,
    TimelineEntry,
    VolumeDayEntry,
)
from app.schemas.common import StatusCounts
from app.services.alert_service import AlertService

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _make_list_item(alert, device, assignee) -> AlertListItem:
    return AlertListItem(
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
    )


@router.get("", response_model=PaginatedAlertsResponse)
def list_alerts(
    severity: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    device_id: str | None = None,
    assigned_to: str | None = None,
    q: str | None = None,
    from_: Annotated[int | None, Query(alias="from")] = None,
    to: int | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedAlertsResponse:
    repo = AlertRepository(db)
    rows, total, status_counts = repo.list_by_company(
        company=current_user.company,
        severity=severity,
        status=status,
        device_id=device_id,
        assigned_to=assigned_to,
        q=q,
        from_ms=from_,
        to_ms=to,
        page=page,
        page_size=page_size,
    )
    return PaginatedAlertsResponse(
        items=[_make_list_item(a, d, u) for a, d, u in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
        status_counts=StatusCounts(**status_counts),
    )


@router.get("/stats", response_model=AlertStatsResponse)
def get_alert_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertStatsResponse:
    import time
    from datetime import datetime, timedelta

    # All company alerts
    base = (
        db.query(Alert)
        .join(Device, Alert.device_id == Device.device_id)
        .filter(Device.company == current_user.company)
    )
    all_alerts = base.all()

    # Status counts
    status_counts: dict[str, int] = {"new": 0, "acknowledged": 0, "resolved": 0, "dismissed": 0}
    for a in all_alerts:
        if a.status in status_counts:
            status_counts[a.status] += 1

    # Severity counts
    severity_counts: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for a in all_alerts:
        if a.severity in severity_counts:
            severity_counts[a.severity] += 1

    # MTTR: mean time from alert created to resolved, in hours.
    resolved = [a for a in all_alerts if a.status == "resolved" and a.resolved_at is not None]
    resolved_durations_ms = [
        a.resolved_at - a.timestamp_utc
        for a in all_alerts
        if a.status == "resolved" and a.resolved_at is not None
    ]
    mttr_hours: float | None = None
    if resolved_durations_ms:
        total_ms = sum(resolved_durations_ms)
        mttr_hours = round(
            (total_ms / len(resolved_durations_ms)) / (1000 * 60 * 60), 2
        )

    # Resolved this week vs last week
    now_ms = int(time.time() * 1000)
    one_week_ms = 7 * 24 * 60 * 60 * 1000
    resolved_this_week = sum(
        1 for a in resolved
        if a.resolved_at is not None and (now_ms - a.resolved_at) <= one_week_ms
    )
    resolved_last_week = sum(
        1 for a in resolved
        if a.resolved_at is not None
        and one_week_ms < (now_ms - a.resolved_at) <= 2 * one_week_ms
    )

    # Dismissal rate
    terminal = status_counts["resolved"] + status_counts["dismissed"]
    dismissal_rate = round(status_counts["dismissed"] / terminal * 100, 1) if terminal > 0 else 0.0

    # Volume over last 7 days (by alert creation date, UTC)
    cutoff_ms = now_ms - one_week_ms
    day_counts: dict[str, int] = {}
    for a in all_alerts:
        if a.timestamp_utc >= cutoff_ms:
            dt = datetime.fromtimestamp(a.timestamp_utc / 1000, tz=UTC)
            day = dt.strftime("%Y-%m-%d")
            day_counts[day] = day_counts.get(day, 0) + 1

    # Fill missing days in last 7
    volume_7d = []
    for i in range(6, -1, -1):
        day = (datetime.now(tz=UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
        volume_7d.append(VolumeDayEntry(date=day, count=day_counts.get(day, 0)))

    # Anomaly count — readings flagged as statistically unusual for this company's devices
    from app.models.sensor_reading import SensorReading
    anomaly_count = (
        db.query(SensorReading)
        .join(Device, SensorReading.device_id == Device.device_id)
        .filter(Device.company == current_user.company, SensorReading.is_anomaly.is_(True))
        .count()
    )

    return AlertStatsResponse(
        total_by_status=StatusCounts(**status_counts),
        total_by_severity=SeverityCounts(**severity_counts),
        mttr_hours=mttr_hours,
        resolved_this_week=resolved_this_week,
        resolved_last_week=resolved_last_week,
        dismissal_rate=dismissal_rate,
        volume_7d=volume_7d,
        anomaly_count=anomaly_count,
    )


@router.post("/bulk/acknowledge", response_model=BulkOperationResult)
def bulk_acknowledge(
    data: BulkAcknowledgeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BulkOperationResult:
    svc = AlertService(db, current_user)
    succeeded, errors = 0, []
    for alert_id in data.alert_ids:
        try:
            svc.acknowledge(alert_id)
            succeeded += 1
        except Exception as e:
            errors.append({"id": alert_id, "error": str(e)})
    return BulkOperationResult(succeeded=succeeded, failed=len(errors), errors=errors)


@router.post("/bulk/assign", response_model=BulkOperationResult)
def bulk_assign(
    data: BulkAssignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BulkOperationResult:
    svc = AlertService(db, current_user)
    req = AssignRequest(assignee_id=data.assignee_id, note=data.note)
    succeeded, errors = 0, []
    for alert_id in data.alert_ids:
        try:
            svc.assign(alert_id, req)
            succeeded += 1
        except Exception as e:
            errors.append({"id": alert_id, "error": str(e)})
    return BulkOperationResult(succeeded=succeeded, failed=len(errors), errors=errors)


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    repo = AlertRepository(db)
    result = repo.get_by_id_and_company(alert_id, current_user.company)
    if result is None:
        raise NotFoundError(detail=f"Alert '{alert_id}' not found.")
    alert, device, assignee = result
    timeline = repo.get_timeline(alert.id)
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


@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
def acknowledge_alert(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    svc = AlertService(db, current_user)
    return svc.acknowledge(alert_id)


@router.post("/{alert_id}/assign", response_model=AlertResponse)
def assign_alert(
    alert_id: str,
    data: AssignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    svc = AlertService(db, current_user)
    return svc.assign(alert_id, data)


@router.post("/{alert_id}/resolve", response_model=AlertResponse)
def resolve_alert(
    alert_id: str,
    data: ResolveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    svc = AlertService(db, current_user)
    return svc.resolve(alert_id, data)


@router.post("/{alert_id}/notes", response_model=AlertResponse)
def add_note(
    alert_id: str,
    data: NoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    svc = AlertService(db, current_user)
    return svc.add_note(alert_id, data)


@router.post("/{alert_id}/dismiss", response_model=AlertResponse)
def dismiss_alert(
    alert_id: str,
    data: DismissRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    svc = AlertService(db, current_user)
    return svc.dismiss(alert_id, data)


@router.post("/{alert_id}/reopen", response_model=AlertResponse)
def reopen_alert(
    alert_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertResponse:
    svc = AlertService(db, current_user)
    return svc.reopen(alert_id)
