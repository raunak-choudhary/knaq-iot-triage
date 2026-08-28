"""Integration tests for the GET /alerts/stats analytics endpoint."""
import time

import pytest

from tests.conftest import auth_headers
from tests.factories.alert_factory import make_alert

ALICE = "token-alice-brookfield"
HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS


@pytest.fixture
def setup(db, seeded_users, seeded_devices):
    return seeded_users


def _stats(client, token=ALICE):
    response = client.get("/alerts/stats", headers=auth_headers(token))
    assert response.status_code == 200
    return response.json()


def test_stats_requires_authentication(client, setup):
    """Unauthenticated requests are rejected before any query runs."""
    assert client.get("/alerts/stats").status_code == 401


def test_stats_empty_company_returns_zeroed_payload(client, setup):
    """A company with no alerts gets zeros and a null MTTR, not an error."""
    body = _stats(client)

    assert body["total_by_status"] == {
        "new": 0,
        "acknowledged": 0,
        "resolved": 0,
        "dismissed": 0,
    }
    assert body["total_by_severity"] == {"critical": 0, "warning": 0, "info": 0}
    assert body["mttr_hours"] is None
    assert body["dismissal_rate"] == 0.0
    assert body["resolved_this_week"] == 0
    assert body["resolved_last_week"] == 0
    assert body["anomaly_count"] == 0


def test_stats_counts_alerts_by_status_and_severity(client, db, setup):
    """Status and severity totals reflect every alert in the company."""
    make_alert(db, device_id="ELV-001", status="new", severity="critical")
    make_alert(db, device_id="ELV-001", status="new", severity="warning")
    make_alert(db, device_id="ELV-002", status="acknowledged", severity="warning")
    make_alert(db, device_id="CMP-001", status="dismissed", severity="info")
    db.commit()

    body = _stats(client)

    assert body["total_by_status"] == {
        "new": 2,
        "acknowledged": 1,
        "resolved": 0,
        "dismissed": 1,
    }
    assert body["total_by_severity"] == {"critical": 1, "warning": 2, "info": 1}


def test_stats_is_scoped_to_the_requesting_company(client, db, setup):
    """Alerts belonging to another company never appear in these totals."""
    make_alert(db, device_id="ELV-001", status="new")       # Brookfield
    make_alert(db, device_id="ELV-003", status="new")       # Hines
    make_alert(db, device_id="CMP-002", status="resolved")  # Hines
    db.commit()

    brookfield = _stats(client, ALICE)
    hines = _stats(client, "token-carol-hines")

    assert brookfield["total_by_status"]["new"] == 1
    assert brookfield["total_by_status"]["resolved"] == 0
    assert hines["total_by_status"]["new"] == 1
    assert hines["total_by_status"]["resolved"] == 1


def test_stats_mttr_is_mean_resolution_time_in_hours(client, db, setup):
    """MTTR averages resolved_at minus created time across resolved alerts."""
    now = int(time.time() * 1000)
    a = make_alert(db, device_id="ELV-001", status="resolved", timestamp_utc=now - 4 * HOUR_MS)
    a.resolved_at = now
    b = make_alert(db, device_id="ELV-002", status="resolved", timestamp_utc=now - 2 * HOUR_MS)
    b.resolved_at = now
    db.commit()

    # (4h + 2h) / 2 = 3h
    assert _stats(client)["mttr_hours"] == 3.0


def test_stats_mttr_ignores_resolved_alerts_with_no_resolved_at(client, db, setup):
    """A resolved row missing resolved_at must not crash or skew the mean."""
    now = int(time.time() * 1000)
    a = make_alert(db, device_id="ELV-001", status="resolved", timestamp_utc=now - 6 * HOUR_MS)
    a.resolved_at = now
    stale = make_alert(db, device_id="ELV-002", status="resolved", timestamp_utc=now - 99 * HOUR_MS)
    stale.resolved_at = None
    db.commit()

    body = _stats(client)
    assert body["mttr_hours"] == 6.0
    assert body["total_by_status"]["resolved"] == 2


def test_stats_splits_resolved_counts_into_this_week_and_last_week(client, db, setup):
    """Resolution recency buckets split on the seven day boundary."""
    now = int(time.time() * 1000)
    recent = make_alert(db, device_id="ELV-001", status="resolved", timestamp_utc=now - 3 * DAY_MS)
    recent.resolved_at = now - 2 * DAY_MS
    older = make_alert(db, device_id="ELV-002", status="resolved", timestamp_utc=now - 12 * DAY_MS)
    older.resolved_at = now - 10 * DAY_MS
    ancient = make_alert(db, device_id="CMP-001", status="resolved", timestamp_utc=now - 40 * DAY_MS)
    ancient.resolved_at = now - 30 * DAY_MS
    db.commit()

    body = _stats(client)
    assert body["resolved_this_week"] == 1
    assert body["resolved_last_week"] == 1


def test_stats_dismissal_rate_uses_terminal_alerts_only(client, db, setup):
    """Dismissal rate is dismissed over (resolved + dismissed), ignoring open alerts."""
    make_alert(db, device_id="ELV-001", status="dismissed")
    make_alert(db, device_id="ELV-002", status="dismissed")
    make_alert(db, device_id="CMP-001", status="dismissed")
    make_alert(db, device_id="ESC-002", status="resolved")
    make_alert(db, device_id="ELV-001", status="new")           # not terminal
    make_alert(db, device_id="ELV-002", status="acknowledged")  # not terminal
    db.commit()

    # 3 dismissed of 4 terminal = 75.0
    assert _stats(client)["dismissal_rate"] == 75.0


def test_stats_volume_always_covers_seven_distinct_days(client, db, setup):
    """volume_7d is gap filled, so charts get seven ordered points regardless of data."""
    now = int(time.time() * 1000)
    make_alert(db, device_id="ELV-001", status="new", timestamp_utc=now)
    db.commit()

    volume = _stats(client)["volume_7d"]
    dates = [entry["date"] for entry in volume]

    assert len(volume) == 7
    assert len(set(dates)) == 7
    assert dates == sorted(dates)
    assert sum(entry["count"] for entry in volume) == 1


def test_stats_volume_excludes_alerts_older_than_seven_days(client, db, setup):
    """Alerts outside the window are counted in totals but not in the volume series."""
    now = int(time.time() * 1000)
    make_alert(db, device_id="ELV-001", status="new", timestamp_utc=now - 30 * DAY_MS)
    db.commit()

    body = _stats(client)
    assert body["total_by_status"]["new"] == 1
    assert sum(entry["count"] for entry in body["volume_7d"]) == 0
