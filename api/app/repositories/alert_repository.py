from typing import cast

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.alert_timeline import AlertTimeline
from app.models.device import Device
from app.models.user import User
from app.repositories.base import BaseRepository


class AlertRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db)

    def list_by_company(
        self,
        company: str,
        severity: list[str] | None = None,
        status: list[str] | None = None,
        device_id: str | None = None,
        assigned_to: str | None = None,
        q: str | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Row[tuple[Alert, Device, User | None]]], int, dict[str, int]]:
        base_query = (
            self.db.query(Alert, Device, User)
            .join(Device, Alert.device_id == Device.device_id)
            .outerjoin(User, Alert.assigned_to == User.id)
            .filter(Device.company == company)
        )
        if severity:
            base_query = base_query.filter(Alert.severity.in_(severity))
        if status:
            base_query = base_query.filter(Alert.status.in_(status))
        if device_id:
            base_query = base_query.filter(Alert.device_id == device_id)
        if assigned_to:
            base_query = base_query.filter(Alert.assigned_to == assigned_to)
        if q:
            pattern = f"%{q}%"
            base_query = base_query.filter(
                Alert.title.ilike(pattern) | Alert.device_id.ilike(pattern)
            )
        if from_ms is not None:
            base_query = base_query.filter(Alert.timestamp_utc >= from_ms)
        if to_ms is not None:
            base_query = base_query.filter(Alert.timestamp_utc <= to_ms)

        total = base_query.count()
        items = (
            base_query.order_by(Alert.timestamp_utc.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        # Status counts across all matching alerts (not just current page)
        status_counts: dict[str, int] = {"new": 0, "acknowledged": 0, "resolved": 0, "dismissed": 0}
        all_statuses = (
            self.db.query(Alert.status)
            .join(Device, Alert.device_id == Device.device_id)
            .filter(Device.company == company)
        )
        if severity:
            all_statuses = all_statuses.filter(Alert.severity.in_(severity))
        if device_id:
            all_statuses = all_statuses.filter(Alert.device_id == device_id)
        if q:
            all_statuses = all_statuses.filter(
                Alert.title.ilike(f"%{q}%") | Alert.device_id.ilike(f"%{q}%")
            )
        for (s,) in all_statuses.all():
            if s in status_counts:
                status_counts[s] += 1

        # outerjoin(User) yields NULL for unassigned alerts; mypy cannot infer that
        # from the query, so the nullability is asserted here.
        return (
            cast(list[Row[tuple[Alert, Device, User | None]]], items),
            total,
            status_counts,
        )

    def get_by_id_and_company(
        self, alert_id: str, company: str
    ) -> Row[tuple[Alert, Device, User | None]] | None:
        result = (
            self.db.query(Alert, Device, User)
            .join(Device, Alert.device_id == Device.device_id)
            .outerjoin(User, Alert.assigned_to == User.id)
            .filter(Alert.id == alert_id, Device.company == company)
            .first()
        )
        return cast(Row[tuple[Alert, Device, User | None]] | None, result)

    def get_timeline(self, alert_id: str) -> list[AlertTimeline]:
        return (
            self.db.query(AlertTimeline)
            .filter(AlertTimeline.alert_id == alert_id)
            .order_by(AlertTimeline.timestamp.asc(), AlertTimeline.id.asc())
            .all()
        )
