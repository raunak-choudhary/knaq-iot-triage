import json
import uuid
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from app.config import settings
from app.models.alert import Alert
from app.models.alert_timeline import AlertTimeline
from app.models.device import Device
from app.models.recovery import Recovery
from app.models.sensor_reading import SensorReading
from app.utils.timezone import epoch_ms_to_local_iso

logger = structlog.get_logger()


def _upsert_devices(db: Session, data_dir: str) -> dict[str, Device]:
    devices_path = Path(data_dir) / "devices.json"
    with open(devices_path, encoding="utf-8") as f:
        devices_data = json.load(f)

    for d in devices_data:
        existing = db.get(Device, d["device_id"])
        if existing is None:
            device = Device(
                device_id=d["device_id"],
                type=d["type"],
                company=d["company"],
                name=d["name"],
                location=d["location"],
                timezone=d["timezone"],
                floor_count=d.get("floor_count"),
                installed_date=d["installed_date"],
                reading_types=d["reading_types"],
                alert_thresholds=d.get("alert_thresholds", {}),
            )
            db.add(device)

    db.flush()
    devices = db.query(Device).all()
    return {d.device_id: d for d in devices}


def _preload_dedup_keys(db: Session) -> tuple[set, set, set]:
    reading_keys: set[tuple[str, int, str]] = set()
    for row in db.query(
        SensorReading.device_id,
        SensorReading.timestamp_utc,
        SensorReading.reading_name,
    ).all():
        reading_keys.add((row.device_id, row.timestamp_utc, row.reading_name))

    alert_keys: set[tuple[str, int]] = set()
    for alert_row in db.query(Alert.device_id, Alert.timestamp_utc).all():
        alert_keys.add((alert_row.device_id, alert_row.timestamp_utc))

    recovery_keys: set[tuple[str, int]] = set()
    for recovery_row in db.query(Recovery.device_id, Recovery.timestamp_utc).all():
        recovery_keys.add((recovery_row.device_id, recovery_row.timestamp_utc))

    return reading_keys, alert_keys, recovery_keys


def _is_malformed(msg: dict) -> bool:
    if not msg.get("device_id"):
        return True
    if not msg.get("message_type"):
        return True
    if msg.get("timestamp") is None:
        return True
    return False


def _check_threshold(value: float, name: str, thresholds: dict) -> bool:
    high_key = f"{name}_high"
    low_key = f"{name}_low"
    if high_key in thresholds and value > thresholds[high_key]:
        return True
    if low_key in thresholds and value < thresholds[low_key]:
        return True
    return False


def run_ingest(db: Session, data_dir: str | None = None) -> dict[str, int]:
    if data_dir is None:
        data_dir = settings.data_dir

    devices = _upsert_devices(db, data_dir)
    reading_keys, alert_keys, recovery_keys = _preload_dedup_keys(db)

    messages_path = Path(data_dir) / "sensor_messages.json"
    with open(messages_path, encoding="utf-8") as f:
        messages = json.load(f)

    counts = {"readings": 0, "alerts": 0, "recoveries": 0, "malformed": 0, "skipped": 0}

    for msg in messages:
        try:
            if _is_malformed(msg):
                logger.warning("malformed_message", msg=str(msg)[:200])
                counts["malformed"] += 1
                continue

            device_id = msg["device_id"]
            msg_type = msg["message_type"]
            timestamp = msg["timestamp"]

            if device_id not in devices:
                logger.warning("unknown_device", device_id=device_id)
                counts["skipped"] += 1
                continue

            device = devices[device_id]

            if msg_type == "reading":
                inputs = msg.get("inputs", [])
                for inp in inputs:
                    name = inp["input_name"]
                    value = float(inp["input_value"])
                    key = (device_id, timestamp, name)

                    if name not in device.reading_types:
                        logger.warning(
                            "unknown_reading_type",
                            device_id=device_id,
                            input_name=name,
                        )
                        is_dup = key in reading_keys
                        if not is_dup:
                            reading_keys.add(key)
                        reading = SensorReading(
                            device_id=device_id,
                            timestamp_utc=timestamp,
                            reading_name=name,
                            reading_value=value,
                            breaches_threshold=False,
                            is_duplicate=is_dup,
                            raw_json=inp,
                        )
                        db.add(reading)
                        counts["readings"] += 1
                        continue

                    is_dup = key in reading_keys
                    if not is_dup:
                        reading_keys.add(key)

                    breaches = False if is_dup else _check_threshold(
                        value, name, device.alert_thresholds
                    )

                    reading = SensorReading(
                        device_id=device_id,
                        timestamp_utc=timestamp,
                        reading_name=name,
                        reading_value=value,
                        breaches_threshold=breaches,
                        is_duplicate=is_dup,
                        raw_json=inp,
                    )
                    db.add(reading)
                    counts["readings"] += 1

            elif msg_type == "alert":
                alert_key = (device_id, timestamp)
                if alert_key in alert_keys:
                    continue
                alert_keys.add(alert_key)

                alert_type = msg.get("alert_type", "unknown")
                severity = msg.get("severity") or "warning"
                title = f"{alert_type.replace('_', ' ').title()} on {device.name}"
                timestamp_local = epoch_ms_to_local_iso(timestamp, device.timezone)

                alert = Alert(
                    id=uuid.uuid4().hex,
                    device_id=device_id,
                    alert_type=alert_type,
                    severity=severity,
                    title=title,
                    threshold=msg.get("threshold"),
                    reading_value=msg.get("reading_value"),
                    reading_name=msg.get("reading_name"),
                    timestamp_utc=timestamp,
                    timestamp_local=timestamp_local,
                    status="new",
                )
                db.add(alert)

                timeline_entry = AlertTimeline(
                    alert_id=alert.id,
                    timestamp=timestamp,
                    action="created",
                    user_name=None,
                    details="Alert created from device message",
                    note=None,
                )
                db.add(timeline_entry)
                counts["alerts"] += 1

            elif msg_type == "recovery":
                recovery_key = (device_id, timestamp)
                is_dup = recovery_key in recovery_keys
                if not is_dup:
                    recovery_keys.add(recovery_key)

                recovery = Recovery(
                    device_id=device_id,
                    alert_type=msg.get("alert_type", "unknown"),
                    severity=msg.get("severity"),
                    timestamp_utc=timestamp,
                    reading_value=msg.get("reading_value"),
                    reading_name=msg.get("reading_name"),
                    is_duplicate=is_dup,
                )
                db.add(recovery)
                counts["recoveries"] += 1

            else:
                logger.warning("unknown_message_type", msg_type=msg_type)
                counts["skipped"] += 1

        except Exception as exc:
            logger.error("ingest_error", error=str(exc), msg=str(msg)[:200])

    db.commit()

    anomalies = _detect_anomalies(db)

    logger.info(
        "ingest_complete",
        readings=counts["readings"],
        alerts=counts["alerts"],
        recoveries=counts["recoveries"],
        malformed=counts["malformed"],
        skipped=counts["skipped"],
        anomalies_flagged=anomalies,
    )
    return counts


def _detect_anomalies(db: Session) -> int:
    """Flag readings that are within threshold range but statistically unusual (|z| > 2)."""
    from collections import defaultdict
    from statistics import mean, stdev

    rows = (
        db.query(SensorReading)
        .filter(
            SensorReading.is_duplicate.is_(False),
            SensorReading.breaches_threshold.is_(False),
        )
        .all()
    )

    groups: dict[tuple, list[SensorReading]] = defaultdict(list)
    for r in rows:
        if r.reading_value is not None:
            groups[(r.device_id, r.reading_name)].append(r)

    flagged = 0
    for readings_in_group in groups.values():
        if len(readings_in_group) < 3:
            continue
        values = [r.reading_value for r in readings_in_group]
        m = mean(values)
        s = stdev(values)
        if s == 0:
            continue
        for r in readings_in_group:
            z = abs(r.reading_value - m) / s
            should_flag = z > 2.0
            if r.is_anomaly != should_flag:
                r.is_anomaly = should_flag
                if should_flag:
                    flagged += 1

    db.commit()
    return flagged
