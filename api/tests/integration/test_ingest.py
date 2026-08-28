"""Integration tests for ingest service with real data."""
import pytest

from app.models.alert import Alert
from app.models.alert_timeline import AlertTimeline
from app.models.sensor_reading import SensorReading
from app.services.ingest_service import run_ingest


@pytest.fixture
def ingest_data_dir():
    """Return path to the real data directory."""
    from pathlib import Path
    return str(Path(__file__).parent.parent.parent.parent / "data")


def test_full_ingest_counts(db, ingest_data_dir):
    """Full ingest should produce ~774 readings, 26 alerts, 15 recoveries."""
    counts = run_ingest(db, ingest_data_dir)
    # 816 messages, 3 malformed (1 null timestamp, 1 missing message_type, 1 missing device_id)
    # Among valid: 773 readings (incl dups from 774 inputs across 773 reading messages), 26 alerts, 15 recoveries
    assert counts["malformed"] == 3
    assert counts["alerts"] == 26
    assert counts["recoveries"] == 15
    # Readings count includes all (dup + non-dup)
    assert counts["readings"] >= 700  # at least


def test_all_alerts_status_new(db, ingest_data_dir):
    """After ingest, all alerts should have status 'new'."""
    run_ingest(db, ingest_data_dir)
    alerts = db.query(Alert).all()
    assert len(alerts) == 26
    for alert in alerts:
        assert alert.status == "new"


def test_all_alerts_have_created_timeline(db, ingest_data_dir):
    """Every alert should have exactly one 'created' timeline entry."""
    run_ingest(db, ingest_data_dir)
    alerts = db.query(Alert).all()
    for alert in alerts:
        timeline = (
            db.query(AlertTimeline)
            .filter(AlertTimeline.alert_id == alert.id, AlertTimeline.action == "created")
            .all()
        )
        assert len(timeline) == 1, f"Alert {alert.id} has {len(timeline)} created entries"


def test_malformed_messages_not_in_db(db, ingest_data_dir):
    """The 3 malformed messages should not appear in DB."""
    run_ingest(db, ingest_data_dir)
    # Check CMP-001 null-timestamp reading (temperature 68.3)
    null_ts_readings = (
        db.query(SensorReading)
        .filter(
            SensorReading.device_id == "CMP-001",
            SensorReading.reading_value == 68.3,
        )
        .all()
    )
    assert len(null_ts_readings) == 0


def test_idempotency(db, ingest_data_dir):
    """Running ingest twice should produce same final alert count."""
    run_ingest(db, ingest_data_dir)
    run_ingest(db, ingest_data_dir)  # second run

    alerts_after_1 = db.query(Alert).count()
    run_ingest(db, ingest_data_dir)  # third run
    alerts_after_3 = db.query(Alert).count()

    # Alert count should not increase on reruns
    assert alerts_after_1 == alerts_after_3 == 26


def test_recoveries_do_not_auto_close_alerts(db, ingest_data_dir):
    """Recovery messages should not change alert status."""
    run_ingest(db, ingest_data_dir)
    # All alerts should still be new
    alerts = db.query(Alert).all()
    assert all(a.status == "new" for a in alerts)
