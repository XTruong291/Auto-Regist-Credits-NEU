import asyncio
import time
import logging
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)


class PrecisionScheduler:
    """High-precision async scheduler with <5ms accuracy."""

    # Tuning constants
    COARSE_SLEEP_MARGIN_MS = 10  # Leave 10ms for busy-wait phase
    FINE_SLEEP_DURATION_MS = 0.1  # Initial fine sleep duration
    BUSY_LOOP_THRESHOLD_US = 500  # Switch to busy-loop < 500us from target
    
    @staticmethod
    def _get_time_ms() -> float:
        """Get current unix time in milliseconds."""
        return time.time() * 1000.0

    @staticmethod
    async def wait_until(target_timestamp: float, offset_ms: int = 0) -> None:
        """
        Wait until target_timestamp with <5ms accuracy.
        
        Uses hybrid approach:
        1. Coarse async sleep until ~10ms before target
        2. Fine-grained busy-wait for final precision
        
        Args:
            target_timestamp: Unix timestamp (seconds) when to trigger
            offset_ms: Additional time offset in milliseconds (default: 0)
        """
        now_s = time.time()
        if target_timestamp > now_s:
            logger.info(
                "--- Đang chờ %.3f giây để đến giờ G ---",
                target_timestamp - now_s,
            )

        # Keep everything in unix timeline to match target_timestamp.
        offset_ms_total = offset_ms
        target_ms = target_timestamp * 1000.0 + offset_ms_total
        
        # Phase 1: Coarse sleep (async, CPU-friendly)
        while True:
            now_ms = PrecisionScheduler._get_time_ms()
            remaining_ms = target_ms - now_ms
            
            if remaining_ms <= 0:
                break
            
            # Sleep until we're within coarse margin
            if remaining_ms > PrecisionScheduler.COARSE_SLEEP_MARGIN_MS:
                sleep_duration = (remaining_ms - PrecisionScheduler.COARSE_SLEEP_MARGIN_MS) / 1000.0
                # Add small jitter to avoid thundering herd
                await asyncio.sleep(max(0.0001, sleep_duration - 0.0005))
            else:
                # Phase 2: Fine-grained busy-wait for final microseconds
                await PrecisionScheduler._busy_wait_final(target_ms)
                break
    
    @staticmethod
    async def _busy_wait_final(target_ms: float) -> None:
        """
        Final busy-wait phase: adaptively approach target with minimal CPU waste.
        Achieves <5ms precision at final stage.
        """
        while True:
            now_ms = PrecisionScheduler._get_time_ms()
            remaining_us = (target_ms - now_ms) * 1000.0
            
            if remaining_us <= 0:
                break
            
            # Adaptive strategy based on remaining time
            if remaining_us > 1000:  # >1ms: yield control
                await asyncio.sleep(0.0001)  # 0.1ms sleep
            elif remaining_us > 100:  # >100us: tight sleep loop
                await asyncio.sleep(0.00001)  # 10us sleep
            else:  # Final 100us: spin-wait for precision
                # High-frequency polling for final microsecond window.
                while PrecisionScheduler._get_time_ms() < target_ms:
                    pass

    @staticmethod
    async def schedule_at(target_timestamp: float, coro_fn: Callable[[], Any], offset_ms: int = 0) -> Any:
        """Schedule coroutine execution at precise target time."""
        await PrecisionScheduler.wait_until(target_timestamp, offset_ms)
        return await coro_fn()

    @staticmethod
    async def schedule_burst(
        target_timestamp: float,
        coro_list: list[Callable[[], Any]],
        offset_ms: int = 0,
    ) -> list[Any]:
        """Schedule burst of coroutines at precise target time."""
        await PrecisionScheduler.wait_until(target_timestamp, offset_ms)
        return await asyncio.gather(*[coro() for coro in coro_list], return_exceptions=True)

    @staticmethod
    def get_current_timestamp() -> float:
        """Get current high-precision timestamp (unix time)."""
        return time.time()

    @staticmethod
    def get_current_perf_time() -> float:
        """Get current high-precision perf counter time (relative, for scheduling)."""
        return time.perf_counter()

    @staticmethod
    async def sleep_precise_ms(milliseconds: float) -> None:
        """Sleep for precise milliseconds with <5ms accuracy."""
        if milliseconds <= 0:
            return
        
        await PrecisionScheduler.wait_until(time.time() + milliseconds / 1000.0)


class JobScheduler:
    """Manages job scheduling and execution."""

    def __init__(self):
        self.scheduled_jobs: dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    async def schedule_job(
        self,
        job_id: str,
        target_timestamp: float,
        coro_fn: Callable[[], Any],
        offset_ms: int = 0,
    ) -> asyncio.Task:
        """Schedule job execution at target time."""
        async with self.lock:
            if job_id in self.scheduled_jobs:
                raise ValueError(f"Job {job_id} already scheduled")

            task = asyncio.create_task(
                PrecisionScheduler.schedule_at(target_timestamp, coro_fn, offset_ms)
            )
            self.scheduled_jobs[job_id] = task
            return task

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel scheduled job."""
        async with self.lock:
            if job_id not in self.scheduled_jobs:
                return False

            task = self.scheduled_jobs[job_id]
            task.cancel()
            del self.scheduled_jobs[job_id]
            return True

    async def get_job_status(self, job_id: str) -> Optional[str]:
        """Get job execution status."""
        async with self.lock:
            if job_id not in self.scheduled_jobs:
                return None

            task = self.scheduled_jobs[job_id]
            if task.done():
                return "completed"
            return "running"

    async def wait_job(self, job_id: str) -> Any:
        """Wait for job completion."""
        async with self.lock:
            if job_id not in self.scheduled_jobs:
                raise ValueError(f"Job {job_id} not found")
            task = self.scheduled_jobs[job_id]

        try:
            return await task
        except asyncio.CancelledError:
            return None
