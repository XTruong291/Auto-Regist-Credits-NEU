import asyncio
# pyrefly: ignore [missing-import]
import httpx
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import time
import uuid
import random
from worker.retry import RetryManager, ErrorClassifier, RetryConfig
from worker.engine import RequestEngine, FastScheduler
from worker.scheduler import PrecisionScheduler, JobScheduler

logger = logging.getLogger(__name__)


@dataclass
class RegistrationJob:
    job_id: str
    username: str
    password: str
    regist_type: str
    course_ids: list[str]
    target_timestamp: float
    status: str = "PENDING"
    result: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class CourseRegistrationWorker:
    def __init__(
        self,
        request_timeout: float = 3.0,
    ):
        limits = httpx.Limits(
            max_connections=200,
            max_keepalive_connections=100,
            keepalive_expiry=30.0,
        )

        default_headers = {
            "Apikey": "pscRBF0zT2Mqo6vMw69YMOH43lRb2RtXBS0EHit2kzv",
            "Clientid": "dtl",
            "Origin": "https://tinchi.neu.edu.vn",
            "Referer": "https://tinchi.neu.edu.vn/",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        self.client = httpx.AsyncClient(
            base_url="https://tinchi-api.neu.edu.vn",
            headers=default_headers,
            limits=limits,
            timeout=httpx.Timeout(request_timeout),
            http2=True,
        )

        self.request_engine = RequestEngine(self.client)
        self.job_scheduler = JobScheduler()
        self.jobs: Dict[str, RegistrationJob] = {}
        self.lock = asyncio.Lock()
        self.proxy_list: list[str] = []
        self.current_proxy_idx = 0
        self.metadata_ready = False

    def get_all_jobs_status(self) -> list[dict]:
        return [
            {
                "job_id": job.job_id,
                "username": job.username,
                "regist_type": job.regist_type,
                "status": job.status,
                "target_timestamp": job.target_timestamp
            }
            for job in self.jobs.values()
        ]

    def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job:
            job.cancel_event.set()
            job.status = "CANCELLED"
            return True
        return False

    async def submit_job(
        self,
        username: str,
        password: str,
        regist_type: str,
        course_ids: list[str],
        target_timestamp: float,
    ) -> str:
        """Submit registration job."""
        job_id = str(uuid.uuid4())
        job = RegistrationJob(
            job_id=job_id,
            username=username,
            password=password,
            regist_type=regist_type,
            course_ids=course_ids,
            target_timestamp=target_timestamp,
        )

        async with self.lock:
            self.jobs[job_id] = job

        await self.job_scheduler.schedule_job(
            job_id,
            target_timestamp,
            lambda: self._execute_job(job),
        )

        logger.info(f"Job {job_id} scheduled for {datetime.fromtimestamp(target_timestamp)}")
        return job_id

    async def _execute_job(self, job: RegistrationJob) -> None:
        """Execute registration job in Camping Mode."""
        try:
            logger.info("--- Bắt đầu chế độ Mai phục (CAMPING) cho Job %s ---", job.job_id)
            job.status = "CAMPING"
            start_time = time.time()
            timeout = 7 * 24 * 3600
            
            token = None
            study_program_id = None
            
            while time.time() - start_time < timeout:
                if job.cancel_event.is_set():
                    logger.info("Job %s đã bị hủy.", job.job_id)
                    job.status = "CANCELLED"
                    break
                    
                try:
                    if token is None or study_program_id is None:
                        logger.info("Đang xác thực tài khoản cho %s...", job.username)
                        token = await self.request_engine.authenticate(job.username, job.password)
                        study_program_id = await self.request_engine.fetch_study_program_id(token)
                    
                    any_available = False
                    for course_id in job.course_ids:
                        if job.cancel_event.is_set():
                            break
                        is_available = await self.request_engine.is_slot_available(token, course_id, study_program_id, job.regist_type)
                        if is_available:
                            any_available = True
                            logger.info("Phát hiện slot trống cho môn %s!", course_id)
                            break
                    
                    if job.cancel_event.is_set():
                        continue

                    if not any_available:
                        await asyncio.sleep(random.uniform(2.5, 4.5))
                        continue
                    
                    logger.info("Có slot trống, bắt đầu bắn request đăng ký...")
                    attempt_results = await self.request_engine.multi_course_register(
                        course_ids=job.course_ids,
                        study_program_id=study_program_id,
                        regist_type=job.regist_type,
                        jwt_token=token,
                    )
                    
                    success_count = 0
                    for course_id, result in attempt_results.items():
                        status_code = result.get("status_code")
                        message = result.get("message", "Unknown response")
                        if result.get("success"):
                            success_count += 1
                            job.result[course_id] = f"OK {status_code} - {message}"
                        else:
                            job.result[course_id] = f"Lỗi/SK {status_code} - {message}"
                    
                    if success_count > 0:
                        logger.info("Job %s: Đăng ký thành công %s môn học", job.job_id, success_count)
                        job.status = "SUCCESS"
                        break
                    else:
                        logger.info("Đăng ký thất bại (chậm chân). Tiếp tục mai phục...")
                        await asyncio.sleep(random.uniform(2.5, 4.5))

                except httpx.HTTPStatusError as e:
                    status_code = e.response.status_code
                    if status_code == 401:
                        logger.warning("Token hết hạn (401), đang tự động lấy token mới...")
                        token = None
                    elif status_code == 429:
                        logger.warning("Bị Rate Limit (429), ngủ 60s...")
                        await asyncio.sleep(60)
                    else:
                        logger.warning("Lỗi HTTP %s, thử lại sau 10s...", status_code)
                        await asyncio.sleep(10)
                except Exception as e:
                    logger.warning("Lỗi hệ thống/Network: %s, thử lại sau 10s...", e)
                    await asyncio.sleep(10)
            else:
                if not job.cancel_event.is_set():
                    logger.info("Job %s đã Timeout sau 7 ngày mai phục.", job.job_id)
                    job.status = "TIMEOUT"

        except Exception as e:
            job.status = "FAILED"
            job.error = str(e)
            logger.exception(f"Job {job.job_id} execution error: {e}")

    async def _warmup_connection(self, target_timestamp: float) -> None:
        warmup_at = target_timestamp - 3.0
        if warmup_at > time.time():
            await PrecisionScheduler.wait_until(warmup_at)
        try:
            await self.client.get("/api/Regist/RegistScheduleStudyUnit", timeout=1.0)
        except Exception:
            # Warm-up is best-effort to establish DNS/TCP/TLS before the critical window.
            return

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status."""
        async with self.lock:
            if job_id not in self.jobs:
                return None

            job = self.jobs[job_id]
            return {
                "job_id": job.job_id,
                "status": job.status,
                "result": job.result,
                "error": job.error,
                "created_at": job.created_at.isoformat(),
            }

    async def set_proxies(self, proxy_list: list[str]) -> None:
        """Set rotation proxy list."""
        async with self.lock:
            self.proxy_list = proxy_list
            self.current_proxy_idx = 0

    def _get_next_proxy(self) -> Optional[str]:
        """Get next proxy in rotation."""
        if not self.proxy_list:
            return None
        proxy = self.proxy_list[self.current_proxy_idx]
        self.current_proxy_idx = (self.current_proxy_idx + 1) % len(self.proxy_list)
        return proxy

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down worker...")
        for task in self.job_scheduler.scheduled_jobs.values():
            task.cancel()
        await self.client.aclose()
        logger.info("Worker shutdown complete")


class WorkerPool:
    def __init__(self, num_workers: int = 4):
        self.workers = [CourseRegistrationWorker() for _ in range(num_workers)]
        self.current_worker_idx = 0
        self.lock = asyncio.Lock()

    async def submit_job(
        self,
        username: str,
        password: str,
        regist_type: str,
        course_ids: list[str],
        target_timestamp: float,
    ) -> str:
        """Submit job to round-robin worker."""
        async with self.lock:
            worker = self.workers[self.current_worker_idx]
            self.current_worker_idx = (self.current_worker_idx + 1) % len(self.workers)

        return await worker.submit_job(username, password, regist_type, course_ids, target_timestamp)

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status from any worker."""
        for worker in self.workers:
            status = await worker.get_job_status(job_id)
            if status:
                return status
        return None

    def get_all_jobs_status(self) -> list[dict]:
        jobs = []
        for worker in self.workers:
            jobs.extend(worker.get_all_jobs_status())
        return jobs
        
    def cancel_job(self, job_id: str) -> bool:
        for worker in self.workers:
            if worker.cancel_job(job_id):
                return True
        return False

    async def shutdown(self) -> None:
        """Shutdown all workers."""
        await asyncio.gather(*[worker.shutdown() for worker in self.workers])
