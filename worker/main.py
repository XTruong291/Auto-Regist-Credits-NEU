import asyncio
import httpx
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import time
import uuid
from worker.retry import RetryManager, ErrorClassifier, RetryConfig
from worker.engine import RequestEngine, FastScheduler
from worker.scheduler import PrecisionScheduler, JobScheduler

logger = logging.getLogger(__name__)


@dataclass
class RegistrationJob:
    job_id: str
    jwt_token: str
    course_ids: list[str]
    target_timestamp: float
    status: str = "pending"
    result: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


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

    async def initialize(self, jwt_token: str, course_ids: list[str]) -> None:
        """Load metadata cache for requested courses."""
        async with self.request_engine.cache_lock:
            missing_ids = [cid for cid in course_ids if cid not in self.request_engine.course_cache]
        if not missing_ids:
            self.metadata_ready = True
            return
        await self.request_engine.fetch_course_metadata(jwt_token, missing_ids)
        self.metadata_ready = True

    async def submit_job(
        self,
        jwt_token: str,
        course_ids: list[str],
        target_timestamp: float,
    ) -> str:
        """Submit registration job."""
        logger.info("Worker startup metadata pre-fetch in progress...")
        await self.initialize(jwt_token, course_ids)

        job_id = str(uuid.uuid4())
        job = RegistrationJob(
            job_id=job_id,
            jwt_token=jwt_token,
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
        """Execute registration job."""
        try:
            logger.info("--- Đã lấy được Job %s từ Queue ---", job.job_id)
            job.status = "running"
            logger.info("Metadata pre-fetch check before wait_until...")
            await self.initialize(job.jwt_token, job.course_ids)

            warmup_task = asyncio.create_task(self._warmup_connection(job.target_timestamp))

            await PrecisionScheduler.wait_until(job.target_timestamp)
            await warmup_task

            # In manual-token mode, StudyProgramID should be provided by integration config.
            study_program_id = "MANUAL"

            logger.info("--- BẮT ĐẦU BẮN REQUEST LÊN NEU ---")
            attempt_result = await self.request_engine.register_course(
                curriculum_ids=job.course_ids,
                study_program_id=study_program_id,
                jwt_token=job.jwt_token,
            )
            status_code = attempt_result.get("status_code")
            message = attempt_result.get("message", "Unknown response")
            for course_id in job.course_ids:
                if status_code is None:
                    job.result[course_id] = message
                else:
                    job.result[course_id] = (
                        f"Lỗi/SK {status_code} - {message}"
                        if not attempt_result.get("success")
                        else f"OK {status_code} - {message}"
                    )

            if attempt_result.get("success"):
                logger.info("Job %s: Registered %s courses", job.job_id, len(job.course_ids))

            job.status = "completed"
        except Exception as e:
            job.status = "failed"
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
        jwt_token: str,
        course_ids: list[str],
        target_timestamp: float,
    ) -> str:
        """Submit job to round-robin worker."""
        async with self.lock:
            worker = self.workers[self.current_worker_idx]
            self.current_worker_idx = (self.current_worker_idx + 1) % len(self.workers)

        return await worker.submit_job(jwt_token, course_ids, target_timestamp)

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status from any worker."""
        for worker in self.workers:
            status = await worker.get_job_status(job_id)
            if status:
                return status
        return None

    async def initialize(self, jwt_token: str) -> None:
        """Initialize all workers metadata cache."""
        await asyncio.gather(*[worker.initialize(jwt_token) for worker in self.workers])

    async def shutdown(self) -> None:
        """Shutdown all workers."""
        await asyncio.gather(*[worker.shutdown() for worker in self.workers])
