import asyncio
import logging
from typing import Optional, Any, Dict, Awaitable, Callable, List
import httpx
from enum import Enum
import random
import copy

logger = logging.getLogger(__name__)


class BurstStrategy(Enum):
    BURST_100MS = 0.1
    BURST_150MS = 0.15
    BURST_200MS = 0.2


class RequestEngine:
    REGIST_URL = "https://tinchi-api.neu.edu.vn/api/Regist/RegistScheduleStudyUnit"
    ALL_COURSES_URL = "https://tinchi-api.neu.edu.vn/api/Regist/GetAllScheduleUnitAllowRegist"

    def __init__(
        self,
        client: httpx.AsyncClient,
        max_concurrent: int = 10,
        num_bursts: int = 4,
        burst_delay_ms: int = 150,
        max_attempts_per_job: int = 10,
    ):
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.num_bursts = num_bursts
        self.burst_delay = burst_delay_ms / 1000.0
        self.max_attempts_per_job = max_attempts_per_job
        self.success_flag = asyncio.Event()
        self.result = None
        self.last_result_detail: Dict[str, Any] = {}
        self.active_tasks: set[asyncio.Task] = set()
        self.course_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_lock = asyncio.Lock()

    def _build_shared_headers(self, jwt_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {jwt_token}",
            "Apikey": "pscRBF0zT2Mqo6vMw69YMOH43lrB2RtXBS0EHit2kzv",
            "Clientid": "dtl",
            "Origin": "https://tinchi.neu.edu.vn",
        }

    async def fetch_course_metadata(self, jwt_token: str, course_ids: List[str]) -> None:
        """Fetch and cache course metadata by CurriculumID for requested courses."""
        headers = self._build_shared_headers(jwt_token)
        study_program_id = "K667480201"
        regist_type = "NKH"
        for course_id in course_ids:
            print(f"👉 Đang xử lý ID gốc truyền vào: '{course_id}'")
            base_id = course_id.split("_", 1)[0]
            print(f"✂️ Kết quả sau khi cắt (sẽ dùng làm ReqParam3): '{base_id}'")
            payload = {
                "ReqParam1": study_program_id,
                "ReqParam2": regist_type,
                "ReqParam3": base_id,
            }
            print(f"📦 Payload chuẩn bị bắn: { {'ReqParam1': study_program_id, 'ReqParam2': regist_type, 'ReqParam3': base_id} }")
            try:
                response = await self.client.post(
                    self.ALL_COURSES_URL,
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    logger.error("Lỗi: Metadata trả về không hợp lệ cho môn %s", course_id)
                    continue

                match = next(
                    (
                        item
                        for item in data
                        if isinstance(item, dict) and item.get("CurriculumID") == course_id
                    ),
                    None,
                )
                if match is None:
                    logger.error("Lỗi: Không tìm thấy lớp %s", course_id)
                    continue

                async with self.cache_lock:
                    self.course_cache[course_id] = match
                logger.info("Đã tải xong metadata cho môn: %s", course_id)
            except Exception as e:
                logger.error("Lỗi tải metadata cho môn %s: %s", course_id, e)

    async def register_course(
        self,
        curriculum_ids: list[str],
        study_program_id: str,
        jwt_token: str,
        refresh_jwt_token: Optional[Callable[[], Awaitable[str]]] = None,
    ) -> Dict[str, Any]:
        self.success_flag.clear()
        self.result = None
        self.last_result_detail = {}

        params = {
            "TurnID": "139",
            "Action": "REGIST",
            "StudyProgramID": "K667480201",
            "RegistType": "NKH",
        }
        headers = self._build_shared_headers(jwt_token)

        async with self.cache_lock:
            cache_snapshot = self.course_cache.copy()

        last_detail: Dict[str, Any] = {
            "success": False,
            "status_code": None,
            "message": "Không có course_id hợp lệ để gửi",
        }

        for course_id in curriculum_ids:
            cached_obj = cache_snapshot.get(course_id)
            if not isinstance(cached_obj, dict):
                logger.error("Lỗi: Không tìm thấy lớp %s trong course_cache", course_id)
                last_detail = {
                    "success": False,
                    "status_code": None,
                    "message": f"Không tìm thấy metadata cho {course_id}",
                }
                continue

            payload_obj = copy.deepcopy(cached_obj)
            payload_obj["IsRegisted"] = False
            payload_obj["isOpen"] = True
            payload_obj["isOpenChilrentTask"] = False

            try:
                response = await self.client.post(
                    "https://tinchi-api.neu.edu.vn/api/Regist/RegistScheduleStudyUnit",
                    params=params,
                    json=[payload_obj],
                    headers=headers,
                    timeout=3.0,
                )
                print(f"🚀 Bắn đạn thành công tới URL: {response.request.url}")

                response_text = response.text
                logger.info("NEU response status=%s body=%s", response.status_code, response_text)

                try:
                    response_payload = response.json()
                    parsed_message = (
                        response_payload.get("message")
                        if isinstance(response_payload, dict)
                        else str(response_payload)
                    )
                except ValueError:
                    parsed_message = response_text

                last_detail = {
                    "success": response.status_code == 200,
                    "status_code": response.status_code,
                    "message": parsed_message or response_text or "No response body",
                }

                if response.status_code == 200:
                    self.result = True
                    self.success_flag.set()
                    return last_detail
            except Exception as e:
                logger.exception("Request attempt failed for %s: %s", course_id, e)
                last_detail = {
                    "success": False,
                    "status_code": None,
                    "message": str(e),
                }

        return last_detail

    async def _attempt_register(
        self,
        curriculum_ids: list[str],
        study_program_id: str,
        jwt_token: str,
    ) -> Dict[str, Any]:
        """Single registration attempt with semaphore control."""
        if self.success_flag.is_set():
            return None

        async with self.semaphore:
            if self.success_flag.is_set():
                return None

            try:
                params = {
                    "TurnID": "139",
                    "Action": "REGIST",
                    "StudyProgramID": study_program_id,
                    "RegistType": "NKH",
                }
                async with self.cache_lock:
                    cache_snapshot = self.course_cache.copy()

                body = []
                missing_ids = []
                for curriculum_id in curriculum_ids:
                    metadata = cache_snapshot.get(curriculum_id)
                    if metadata is None:
                        missing_ids.append(curriculum_id)
                        continue
                    enriched = copy.deepcopy(metadata)
                    enriched["IsRegisted"] = False
                    enriched["isOpen"] = True
                    enriched["isOpenChilrentTask"] = False
                    body.append(enriched)

                if missing_ids:
                    logger.error("Missing metadata in cache for CurriculumID: %s", missing_ids)

                if not body:
                    return {
                        "kind": "failure",
                        "status_code": None,
                        "message": "No valid courses found in metadata cache",
                    }

                logger.info("Prepared full payload for %s courses", len(body))
                headers = self._build_shared_headers(jwt_token)
                response = await self.client.post(
                    self.REGIST_URL,
                    params=params,
                    json=body,
                    headers=headers,
                    timeout=3.0,
                )
                response_text = response.text
                logger.info("NEU response status=%s body=%s", response.status_code, response_text)

                try:
                    response_payload = response.json()
                    parsed_message = response_payload.get("message") if isinstance(response_payload, dict) else str(response_payload)
                except ValueError:
                    parsed_message = response_text

                detail = {
                    "status_code": response.status_code,
                    "message": parsed_message or response_text or "No response body",
                }

                if response.status_code == 200:
                    self.result = True
                    self.success_flag.set()
                    return {"kind": "success", **detail}

                if response.status_code == 401:
                    return {"kind": "unauthorized", **detail}

                if response.status_code in (403, 429):
                    return {"kind": "rate_limited", **detail}

                if response.status_code in (400, 409):
                    return {"kind": "failure", **detail}

                if response.status_code >= 500:
                    return {"kind": "retryable", **detail}

                return {"kind": "failure", **detail}

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("Request attempt failed: %s", e)
                return {"kind": "retryable", "status_code": None, "message": str(e)}

    async def multi_course_register(
        self,
        course_ids: list[str],
        study_program_id: str,
        jwt_token: str,
    ) -> Dict[str, bool]:
        """Register multiple courses concurrently."""
        tasks = [
            self.register_course(
                curriculum_ids=[course_id],
                study_program_id=study_program_id,
                jwt_token=jwt_token,
            )
            for course_id in course_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            course_id: bool(result) if not isinstance(result, Exception) else False
            for course_id, result in zip(course_ids, results)
        }


class FastScheduler:
    @staticmethod
    async def wait_until(target_timestamp: float, offset_ms: int = 0) -> None:
        """High-precision wait using PrecisionScheduler."""
        from worker.scheduler import PrecisionScheduler
        await PrecisionScheduler.wait_until(target_timestamp, offset_ms)


class RetryStrategy:
    class ErrorType(Enum):
        LOGIN_FAILED = "login_failed"
        SLOT_FULL = "slot_full"
        RATE_LIMIT = "rate_limit"
        SERVER_ERROR = "server_error"
        NETWORK_ERROR = "network_error"
        SUCCESS = "success"

    @staticmethod
    def classify_error(status_code: Optional[int], exception: Optional[Exception]) -> str:
        if exception is None and status_code == 200:
            return RetryStrategy.ErrorType.SUCCESS.value

        if isinstance(exception, asyncio.TimeoutError):
            return RetryStrategy.ErrorType.NETWORK_ERROR.value

        if status_code == 401:
            return RetryStrategy.ErrorType.LOGIN_FAILED.value

        if status_code == 409:
            return RetryStrategy.ErrorType.SLOT_FULL.value

        if status_code == 429:
            return RetryStrategy.ErrorType.RATE_LIMIT.value

        if status_code and status_code >= 500:
            return RetryStrategy.ErrorType.SERVER_ERROR.value

        return RetryStrategy.ErrorType.NETWORK_ERROR.value

    @staticmethod
    async def retry_with_backoff(
        coro_fn,
        max_retries: int = 3,
        base_delay_ms: int = 10,
    ) -> Any:
        """Exponential backoff retry."""
        for attempt in range(max_retries):
            try:
                return await coro_fn()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                delay = (base_delay_ms * (2 ** attempt)) / 1000.0
                await asyncio.sleep(delay)
