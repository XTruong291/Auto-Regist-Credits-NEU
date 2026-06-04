import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(delete=False).name}"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/1"

import anyio
import httpx

from app.db import Base, JobEvent, SessionLocal, engine
from app.main import app
from worker.engine import RequestEngine


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_neu_login_success(monkeypatch):
    async def fake_authenticate(self, username, password):
        return "neu-token"

    monkeypatch.setattr(RequestEngine, "authenticate", fake_authenticate)

    async def run():
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            return await client.post(
                "/auth/neu/login",
                json={"neu_username": "112233", "neu_password": "secret"},
            )

    response = anyio.run(run)

    assert response.status_code == 200
    data = response.json()
    assert data["neu_token"] == "neu-token"
    assert data["token_type"] == "Bearer"
    assert data["neu_username"] == "112233"
    assert "neu_password" not in data


def test_extract_token_accepts_common_response_shapes():
    engine = RequestEngine(client=None)

    assert engine._extract_token({"Token": "A"}) == "A"
    assert engine._extract_token({"token": "B"}) == "B"
    assert engine._extract_token({"data": {"access_token": "C"}}) == "C"
    assert engine._extract_token({"Result": {"JWT": "D"}}) == "D"


def test_neu_login_failure(monkeypatch):
    async def fake_authenticate(self, username, password):
        raise Exception("bad credentials")

    monkeypatch.setattr(RequestEngine, "authenticate", fake_authenticate)

    async def run():
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            return await client.post(
                "/auth/neu/login",
                json={"neu_username": "112233", "neu_password": "wrong"},
            )

    response = anyio.run(run)

    assert response.status_code == 401


def test_create_job_requires_neu_token():
    async def run():
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            return await client.post(
                "/jobs",
                json={
                    "regist_type": "NKH",
                    "course_ids": ["ABC123"],
                    "target_timestamp": 1893456000.0,
                },
            )

    response = anyio.run(run)

    assert response.status_code == 401


def test_create_and_read_job_with_neu_token(monkeypatch):
    async def fake_authenticate(self, username, password):
        return "neu-token"

    class FakeCeleryTask:
        @staticmethod
        def delay(job_id):
            return None

    monkeypatch.setattr(RequestEngine, "authenticate", fake_authenticate)
    monkeypatch.setattr("app.main.run_registration_job", FakeCeleryTask)

    async def run():
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            login = await client.post(
                "/auth/neu/login",
                json={"neu_username": "112233", "neu_password": "secret"},
            )
            token = login.json()["neu_token"]

            created = await client.post(
                "/jobs",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "regist_type": "NKH",
                    "course_ids": ["ABC123"],
                    "target_timestamp": 1893456000.0,
                },
            )
            job_id = created.json()["job_id"]
            status = await client.get(f"/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
            return created, status, job_id

    created, status, job_id = anyio.run(run)
    assert created.status_code == 201

    assert status.status_code == 200
    assert status.json()["job_id"] == job_id
    assert status.json()["status"] == "QUEUED"
    assert status.json()["course_ids"] == ["ABC123"]


def test_read_job_events_with_neu_token(monkeypatch):
    async def fake_authenticate(self, username, password):
        return "neu-token"

    class FakeCeleryTask:
        @staticmethod
        def delay(job_id):
            return None

    monkeypatch.setattr(RequestEngine, "authenticate", fake_authenticate)
    monkeypatch.setattr("app.main.run_registration_job", FakeCeleryTask)

    async def run():
        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            login = await client.post(
                "/auth/neu/login",
                json={"neu_username": "112233", "neu_password": "secret"},
            )
            token = login.json()["neu_token"]
            created = await client.post(
                "/jobs",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "regist_type": "NKH",
                    "course_ids": ["ABC123"],
                    "target_timestamp": 1893456000.0,
                },
            )
            job_id = created.json()["job_id"]

            db = SessionLocal()
            try:
                db.add(
                    JobEvent(
                        job_id=job_id,
                        event_type="slot_scan",
                        message="Đã quét slot môn ABC123",
                        metadata_json={"course_id": "ABC123", "available": False},
                    )
                )
                db.commit()
            finally:
                db.close()

            response = await client.get(f"/jobs/{job_id}/events", headers={"Authorization": f"Bearer {token}"})
            return response

    response = anyio.run(run)

    assert response.status_code == 200
    events = response.json()
    assert events[0]["event_type"] == "slot_scan"
    assert events[0]["metadata"]["course_id"] == "ABC123"
