import random
import string
import asyncio
from typing import List


def generate_request_id(prefix: str = "req") -> str:
    """Generate unique request ID."""
    random_suffix = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    return f"{prefix}_{random_suffix}"


def calculate_next_burst_time(current_time: float, burst_delay_ms: int) -> float:
    """Calculate next burst execution time."""
    return current_time + (burst_delay_ms / 1000.0)


async def rate_limiter(call_count: int, period_seconds: int):
    """Simple async rate limiter."""
    for _ in range(call_count):
        yield
        await asyncio.sleep(period_seconds / call_count)


class CircuitBreaker:
    """Simple circuit breaker pattern."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"

    def record_success(self):
        """Record successful operation."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def is_available(self) -> bool:
        """Check if operation is available."""
        if self.state == "closed":
            return True

        if self.state == "open":
            current_time = asyncio.get_event_loop().time()
            if current_time - self.last_failure_time > self.recovery_timeout:
                self.state = "half_open"
                return True
            return False

        return self.state == "half_open"
