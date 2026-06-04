import asyncio
import logging
import random
import time

import httpx

from app.db import RegistrationJob, SessionLocal, init_db, record_job_event, utc_now
from config import AppConfig
from worker.celery_app import celery_app
from worker.engine import RequestEngine
from worker.scheduler import PrecisionScheduler

logger = logging.getLogger(__name__)


def _set_job_status(job_id: str, status: str, error: str | None = None, result: dict | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.get(RegistrationJob, job_id)
        if job is None:
            return
        job.status = status
        job.updated_at = utc_now()
        if error is not None:
            job.error = error
        if result is not None:
            job.result = result
        db.commit()
    finally:
        db.close()


def _is_cancel_requested(job_id: str) -> bool:
    db = SessionLocal()
    try:
        job = db.get(RegistrationJob, job_id)
        return bool(job is None or job.cancel_requested or job.status == "CANCELLED")
    finally:
        db.close()


def _record_event(job_id: str, event_type: str, message: str, metadata: dict | None = None) -> None:
    db = SessionLocal()
    try:
        record_job_event(db, job_id, event_type, message, metadata)
    finally:
        db.close()


async def _run_registration_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(RegistrationJob, job_id)
        if job is None:
            logger.warning("Job %s not found", job_id)
            return
        account = job.account
        neu_username = account.neu_username
        neu_password = account.neu_password
        regist_type = job.regist_type
        course_ids = list(job.course_ids or [])
        target_timestamp = job.target_timestamp
    finally:
        db.close()

    if _is_cancel_requested(job_id):
        _set_job_status(job_id, "CANCELLED")
        return

    timeout = AppConfig.WORKER_CONFIG.JOB_TIMEOUT_SECONDS
    scan_min = AppConfig.WORKER_CONFIG.SCAN_INTERVAL_MIN_SECONDS
    scan_max = AppConfig.WORKER_CONFIG.SCAN_INTERVAL_MAX_SECONDS
    start_time = time.time()

    limits = httpx.Limits(
        max_connections=AppConfig.WORKER_CONFIG.MAX_CONNECTIONS,
        max_keepalive_connections=AppConfig.WORKER_CONFIG.MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry=30.0,
    )

    async with httpx.AsyncClient(
        base_url="https://tinchi-api.neu.edu.vn",
        limits=limits,
        timeout=httpx.Timeout(AppConfig.WORKER_CONFIG.REQUEST_TIMEOUT_SECONDS),
        http2=True,
    ) as client:
        engine = RequestEngine(client)
        token = None
        study_program_id = None

        try:
            _set_job_status(job_id, "CAMPING")
            _record_event(job_id, "camping_started", "Bắt đầu camping mode")

            if target_timestamp > time.time():
                await PrecisionScheduler.wait_until(target_timestamp)

            while time.time() - start_time < timeout:
                if _is_cancel_requested(job_id):
                    _set_job_status(job_id, "CANCELLED")
                    _record_event(job_id, "cancelled", "Job đã bị hủy")
                    return

                try:
                    if token is None or study_program_id is None:
                        _record_event(job_id, "login", "Đang xác thực tài khoản NEU")
                        token = await engine.authenticate(neu_username, neu_password)
                        study_program_id = await engine.fetch_study_program_id(token)
                        _record_event(job_id, "login_success", "Xác thực NEU thành công")

                    any_available = False
                    for course_id in course_ids:
                        if _is_cancel_requested(job_id):
                            _set_job_status(job_id, "CANCELLED")
                            return
                        available = await engine.is_slot_available(token, course_id, study_program_id, regist_type)
                        _record_event(
                            job_id,
                            "slot_scan",
                            f"Đã quét slot môn {course_id}",
                            {"course_id": course_id, "available": available},
                        )
                        if available:
                            any_available = True
                            _record_event(job_id, "slot_found", f"Phát hiện slot trống môn {course_id}")
                            break

                    if not any_available:
                        await asyncio.sleep(random.uniform(scan_min, scan_max))
                        continue

                    _set_job_status(job_id, "RUNNING")
                    _record_event(job_id, "register_attempt", "Bắt đầu gọi API đăng ký")
                    attempt_results = await engine.multi_course_register(
                        course_ids=course_ids,
                        study_program_id=study_program_id,
                        regist_type=regist_type,
                        jwt_token=token,
                    )

                    success_count = sum(1 for result in attempt_results.values() if result.get("success"))
                    _set_job_status(
                        job_id,
                        "SUCCESS" if success_count > 0 else "CAMPING",
                        result=attempt_results,
                    )
                    _record_event(
                        job_id,
                        "register_result",
                        f"Kết quả đăng ký: {success_count}/{len(course_ids)} môn thành công",
                        {"success_count": success_count, "total": len(course_ids)},
                    )
                    if success_count > 0:
                        return

                    await asyncio.sleep(random.uniform(scan_min, scan_max))

                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else None
                    if status_code == 401:
                        token = None
                        _record_event(job_id, "token_expired", "Token NEU hết hạn, sẽ đăng nhập lại")
                    elif status_code == 429:
                        _record_event(job_id, "rate_limited", "NEU trả 429, tạm nghỉ 60 giây")
                        await asyncio.sleep(60)
                    else:
                        _record_event(job_id, "http_error", f"Lỗi HTTP {status_code}, thử lại sau 10 giây")
                        await asyncio.sleep(10)
                except Exception as exc:
                    _record_event(job_id, "worker_error", f"Lỗi worker: {exc}")
                    await asyncio.sleep(10)

            _set_job_status(job_id, "TIMEOUT", error="Job timeout")
            _record_event(job_id, "timeout", "Job đã timeout")

        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            _set_job_status(job_id, "FAILED", error=str(exc))
            _record_event(job_id, "failed", f"Job thất bại: {exc}")


@celery_app.task(name="worker.tasks.run_registration_job")
def run_registration_job(job_id: str) -> None:
    init_db()
    asyncio.run(_run_registration_job(job_id))
