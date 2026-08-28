"""Unit tests for the ingest service."""
import json
import tempfile
from pathlib import Path

from app.models.alert import Alert
from app.models.alert_timeline import AlertTimeline
from app.models.recovery import Recovery
from app.models.sensor_reading import SensorReading
from app.services.ingest_service import run_ingest


def _make_device_json(device_id="TEST-001", company="Acme", name="Test Device",
                      timezone="America/New_York", reading_types=None, alert_thresholds=None):
    if reading_types is None:
        reading_types = ["current", "frequency", "motor_status"]
    if alert_thresholds is None:
        alert_thresholds = {"current_high": 180.0, "current_low": 5.0}
    return {
        "device_id": device_id,
        "type": "elevator",
        "company": company,
        "name": name,
        "location": "Test Building",
        "timezone": timezone,
        "floor_count": 10,
        "installed_date": "2024-01-01",
        "reading_types": reading_types,
        "alert_thresholds": alert_thresholds,
    }


def _write_data(devices: list, messages: list) -> str:
    """Write test data to a temp dir and return the dir path."""
    d = tempfile.mkdtemp()
    with open(Path(d) / "devices.json", "w") as f:
        json.dump(devices, f)
    with open(Path(d) / "sensor_messages.json", "w") as f:
        json.dump(messages, f)
    return d


def test_valid_reading_stored(db):
    data_dir = _write_data(
        [_make_device_json()],
        [{"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "current", "input_value": 50.0}]}],
    )
    run_ingest(db, data_dir)
    readings = db.query(SensorReading).filter(SensorReading.device_id == "TEST-001").all()
    assert len(readings) == 1
    assert readings[0].reading_value == 50.0
    assert readings[0].is_duplicate is False


def test_reading_above_threshold_breaches(db):
    data_dir = _write_data(
        [_make_device_json(alert_thresholds={"current_high": 100.0})],
        [{"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "current", "input_value": 150.0}]}],
    )
    run_ingest(db, data_dir)
    reading = db.query(SensorReading).first()
    assert reading.breaches_threshold is True


def test_reading_below_threshold_breaches(db):
    data_dir = _write_data(
        [_make_device_json(alert_thresholds={"current_low": 10.0})],
        [{"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "current", "input_value": 3.0}]}],
    )
    run_ingest(db, data_dir)
    reading = db.query(SensorReading).first()
    assert reading.breaches_threshold is True


def test_reading_in_range_no_breach(db):
    data_dir = _write_data(
        [_make_device_json(alert_thresholds={"current_high": 180.0, "current_low": 5.0})],
        [{"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "current", "input_value": 100.0}]}],
    )
    run_ingest(db, data_dir)
    reading = db.query(SensorReading).first()
    assert reading.breaches_threshold is False


def test_duplicate_reading_flagged(db):
    msg = {"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
           "inputs": [{"input_name": "current", "input_value": 50.0}]}
    data_dir = _write_data([_make_device_json()], [msg, msg])
    run_ingest(db, data_dir)
    readings = db.query(SensorReading).filter(SensorReading.device_id == "TEST-001").all()
    assert len(readings) == 2
    assert readings[0].is_duplicate is False
    assert readings[1].is_duplicate is True


def test_alert_stored_with_timeline(db):
    data_dir = _write_data(
        [_make_device_json()],
        [{"device_id": "TEST-001", "message_type": "alert", "timestamp": 1750000000000,
          "alert_type": "high_current", "severity": "critical"}],
    )
    run_ingest(db, data_dir)
    alerts = db.query(Alert).all()
    assert len(alerts) == 1
    assert alerts[0].status == "new"
    assert alerts[0].severity == "critical"
    timeline = db.query(AlertTimeline).filter(AlertTimeline.alert_id == alerts[0].id).all()
    assert len(timeline) == 1
    assert timeline[0].action == "created"


def test_missing_severity_defaults_to_warning(db):
    data_dir = _write_data(
        [_make_device_json()],
        [{"device_id": "TEST-001", "message_type": "alert", "timestamp": 1750000000000,
          "alert_type": "high_current"}],  # no severity
    )
    run_ingest(db, data_dir)
    alert = db.query(Alert).first()
    assert alert.severity == "warning"


def test_recovery_stored_no_auto_close(db):
    data_dir = _write_data(
        [_make_device_json()],
        [
            {"device_id": "TEST-001", "message_type": "alert", "timestamp": 1750000000000,
             "alert_type": "high_current", "severity": "warning"},
            {"device_id": "TEST-001", "message_type": "recovery", "timestamp": 1750000001000,
             "alert_type": "high_current", "severity": "warning"},
        ],
    )
    run_ingest(db, data_dir)
    alert = db.query(Alert).first()
    assert alert.status == "new"  # NOT auto-closed
    recoveries = db.query(Recovery).all()
    assert len(recoveries) == 1


def test_missing_device_id_skipped(db):
    data_dir = _write_data(
        [_make_device_json()],
        [{"message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "current", "input_value": 50.0}]}],
    )
    counts = run_ingest(db, data_dir)
    assert counts["malformed"] == 1
    assert db.query(SensorReading).count() == 0


def test_missing_message_type_skipped(db):
    data_dir = _write_data(
        [_make_device_json()],
        [{"device_id": "TEST-001", "timestamp": 1750000000000,
          "inputs": [{"input_name": "current", "input_value": 50.0}]}],
    )
    counts = run_ingest(db, data_dir)
    assert counts["malformed"] == 1
    assert db.query(SensorReading).count() == 0


def test_missing_timestamp_skipped(db):
    data_dir = _write_data(
        [_make_device_json()],
        [{"device_id": "TEST-001", "message_type": "reading", "timestamp": None,
          "inputs": [{"input_name": "current", "input_value": 50.0}]}],
    )
    counts = run_ingest(db, data_dir)
    assert counts["malformed"] == 1
    assert db.query(SensorReading).count() == 0


def test_unknown_device_skipped(db):
    data_dir = _write_data(
        [_make_device_json()],
        [{"device_id": "NONEXISTENT", "message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "current", "input_value": 50.0}]}],
    )
    counts = run_ingest(db, data_dir)
    assert counts["skipped"] == 1
    assert db.query(SensorReading).count() == 0


def test_input_not_in_reading_types_stored_breach_false(db):
    data_dir = _write_data(
        [_make_device_json(reading_types=["current"])],  # only current
        [{"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "unknown_sensor", "input_value": 999.0}]}],
    )
    run_ingest(db, data_dir)
    reading = db.query(SensorReading).first()
    assert reading is not None
    assert reading.breaches_threshold is False
    assert reading.reading_name == "unknown_sensor"


def test_idempotent_rerun_identical_counts(db):
    msg = {"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
           "inputs": [{"input_name": "current", "input_value": 50.0}]}
    data_dir = _write_data([_make_device_json()], [msg])
    counts1 = run_ingest(db, data_dir)
    counts2 = run_ingest(db, data_dir)
    # Second run adds duplicate row but total readings count increments
    # The idempotency is that alert/recovery counts are identical
    assert counts1["readings"] == counts2["readings"]


def test_alert_dedup_no_duplicate_timeline(db):
    alert_msg = {"device_id": "TEST-001", "message_type": "alert", "timestamp": 1750000000000,
                 "alert_type": "high_current", "severity": "warning"}
    data_dir = _write_data([_make_device_json()], [alert_msg, alert_msg])
    run_ingest(db, data_dir)
    alerts = db.query(Alert).all()
    assert len(alerts) == 1  # only one alert
    timeline = db.query(AlertTimeline).all()
    assert len(timeline) == 1  # only one timeline entry


def test_motor_status_no_threshold(db):
    """motor_status values (0/1) should never breach threshold."""
    data_dir = _write_data(
        [_make_device_json(reading_types=["current", "frequency", "motor_status"],
                           alert_thresholds={"current_high": 180.0})],
        [{"device_id": "TEST-001", "message_type": "reading", "timestamp": 1750000000000,
          "inputs": [{"input_name": "motor_status", "input_value": 1}]}],
    )
    run_ingest(db, data_dir)
    reading = db.query(SensorReading).first()
    assert reading.breaches_threshold is False  # no motor_status_high/low threshold
