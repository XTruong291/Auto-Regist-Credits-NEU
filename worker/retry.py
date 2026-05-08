import asyncio
import logging
from typing import Optional, Callable, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorClassifier(Enum):
    LOGIN_FAILED = "login_failed"
    SLOT_FULL = "slot_full"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN_ERROR = "unknown_error"
    SUCCESS = "success"


class RetryConfig:
    def __init__(
        self,
        max_retries: int = 3,
        base_delay_ms: int = 10,
        max_delay_ms: int = 1000,
        exponential_base: float = 2.0,
    ):
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms
        self.exponential_base = exponential_base


class RetryManager:
    @staticmethod
    def classify_error(
        status_code: Optional[int] = None, exception: Optional[Exception] = None
    ) -> ErrorClassifier:
        """Classify error type for retry decisions."""
        if status_code is None and exception is None:
            return ErrorClassifier.SUCCESS

        if isinstance(exception, asyncio.TimeoutError):
            return ErrorClassifier.NETWORK_ERROR

        if status_code == 401:
            return ErrorClassifier.LOGIN_FAILED

        if status_code == 409:
            return ErrorClassifier.SLOT_FULL

        if status_code == 429:
            return ErrorClassifier.RATE_LIMIT

        if status_code and status_code >= 500:
            return ErrorClassifier.SERVER_ERROR

        if exception:
            return ErrorClassifier.NETWORK_ERROR

        return ErrorClassifier.UNKNOWN_ERROR

    @staticmethod
    async def execute_with_retry(
        coro_fn: Callable[[], Any],
        config: RetryConfig = None,
        on_retry: Optional[Callable[[int, Exception], None]] = None,
    ) -> Any:
        """Execute coroutine with exponential backoff retry."""
        if config is None:
            config = RetryConfig()

        last_exception = None

        for attempt in range(config.max_retries):
            try:
                return await coro_fn()
            except Exception as e:
                last_exception = e
                if attempt < config.max_retries - 1:
                    delay_ms = min(
                        config.base_delay_ms * (config.exponential_base ** attempt),
                        config.max_delay_ms,
                    )
                    if on_retry:
                        on_retry(attempt + 1, e)
                    await asyncio.sleep(delay_ms / 1000.0)

        raise last_exception

    @staticmethod
    def should_retry(error_classifier: ErrorClassifier) -> bool:
        """Determine if error should trigger immediate retry."""
        return error_classifier not in (
            ErrorClassifier.LOGIN_FAILED,
            ErrorClassifier.SLOT_FULL,
        )
