import asyncio
import logging
from typing import Optional, Callable, Any
from enum import Enum
# pyrefly: ignore [missing-import]
import httpx

logger = logging.getLogger(__name__)


class ErrorClassifier(Enum):
    BAD_REQUEST = "bad_request"
    LOGIN_FAILED = "login_failed"
    FORBIDDEN = "forbidden"
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
        if isinstance(exception, httpx.HTTPStatusError) and exception.response is not None:
            status_code = exception.response.status_code

        if status_code is None and exception is None:
            return ErrorClassifier.SUCCESS

        if isinstance(exception, (asyncio.TimeoutError, httpx.TimeoutException, httpx.NetworkError)):
            return ErrorClassifier.NETWORK_ERROR

        if status_code == 400:
            return ErrorClassifier.BAD_REQUEST

        if status_code == 401:
            return ErrorClassifier.LOGIN_FAILED

        if status_code == 403:
            return ErrorClassifier.FORBIDDEN

        if status_code == 409:
            return ErrorClassifier.SLOT_FULL

        if status_code == 429:
            return ErrorClassifier.RATE_LIMIT

        if status_code and status_code >= 500:
            return ErrorClassifier.SERVER_ERROR

        if exception:
            return ErrorClassifier.NETWORK_ERROR

        return ErrorClassifier.UNKNOWN_ERROR

    @classmethod
    async def execute_with_retry(
        cls,
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
                error_class = cls.classify_error(exception=e)
                if not cls.should_retry(error_class):
                    raise e
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
        return error_classifier in (
            ErrorClassifier.RATE_LIMIT,
            ErrorClassifier.SERVER_ERROR,
            ErrorClassifier.NETWORK_ERROR,
        )
