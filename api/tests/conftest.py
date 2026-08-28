import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Add api/ root to sys.path so 'scripts' is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, get_db
from app.main import create_app
from app.models.device import Device
from app.models.user import User

TEST_DB_URL = "sqlite:///./test_knaq.db"


def _set_wal(dbapi_connection, connection_record):  # noqa: ARG001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    event.listen(eng, "connect", _set_wal)
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()
    # clean up db file
    import time
    db_path = Path("./test_knaq.db")
    for _ in range(5):
        try:
            if db_path.exists():
                db_path.unlink()
            break
        except PermissionError:
            time.sleep(0.2)


@pytest.fixture(scope="session")
def session_maker(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db(session_maker):
    """Provide a clean database session for each test, rolled back after."""
    connection = session_maker.kw["bind"].connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection)
    session = session_factory()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db):
    """Test client with overridden get_db dependency."""
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="function")
def seeded_users(db):
    """Seed all 6 users into the test DB."""
    from scripts.seed_users import SEED_USERS

    users = {}
    for data in SEED_USERS:
        existing = db.query(User).filter(User.token == data["token"]).first()
        if existing is None:
            user = User(
                id=uuid.uuid4().hex,
                name=data["name"],
                role=data["role"],
                company=data["company"],
                token=data["token"],
            )
            db.add(user)
        else:
            user = existing
        users[data["token"]] = user
    db.commit()
    return users


@pytest.fixture(scope="function")
def seeded_devices(db):
    """Seed all 10 devices from devices.json."""
    data_path = Path(__file__).parent.parent.parent / "data" / "devices.json"
    with open(data_path, encoding="utf-8") as f:
        devices_data = json.load(f)

    devices = {}
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
        else:
            device = existing
        devices[d["device_id"]] = device
    db.commit()
    return devices


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
