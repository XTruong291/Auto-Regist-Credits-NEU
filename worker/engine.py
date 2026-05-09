import asyncio
import logging
from typing import Optional, Any, Dict, Awaitable, Callable, List
# pyrefly: ignore [missing-import]
import httpx
from enum import Enum
import random
import copy
from worker.retry import RetryManager, RetryConfig

logger = logging.getLogger(__name__)


class RequestEngine:
    REGIST_URL = "https://tinchi-api.neu.edu.vn/api/Regist/RegistScheduleStudyUnit"
    ALL_COURSES_URL = "https://tinchi-api.neu.edu.vn/api/Regist/GetAllScheduleUnitAllowRegist"
    AUTH_URL = "https://tinchi-api.neu.edu.vn/api/Authen/Authenticate"
    STUDY_PROGRAM_URL = "https://tinchi-api.neu.edu.vn/api/Authen/GetAllStudyProgramRegist"

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

    def _build_shared_headers(self, jwt_token: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Apikey": "pscRBF0zT2Mqo6vMw69YMOH43lrB2RtXBS0EHit2kzv",
            "Clientid": "dtl",
            "Origin": "https://tinchi.neu.edu.vn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
        return headers

    async def authenticate(self, username: str, password: str) -> str:
        headers = self._build_shared_headers(jwt_token=None)
        headers["Content-Type"] = "application/json"
        try:
            response = await self.client.post(
                self.AUTH_URL,
                json={"username": username, "password": password},
                headers=headers,
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            if "Token" not in data:
                raise ValueError("Không tìm thấy Token trong response đăng nhập")
            logger.info("Đăng nhập thành công, đã lấy được Token.")
            return data["Token"]
        except Exception as e:
            logger.error("Lỗi đăng nhập: %s", e)
            raise Exception(f"Đăng nhập thất bại: {e}")

    async def fetch_study_program_id(self, jwt_token: str) -> str:
        headers = self._build_shared_headers(jwt_token)
        try:
            response = await self.client.get(
                self.STUDY_PROGRAM_URL,
                headers=headers,
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            if not data or not isinstance(data, list):
                raise ValueError("Response Study Program không hợp lệ")
            study_program_id = data[0].get("StudyProgramID")
            if not study_program_id:
                raise ValueError("Không tìm thấy StudyProgramID trong object trả về")
            logger.info("Đã lấy được StudyProgramID: %s", study_program_id)
            return study_program_id
        except Exception as e:
            logger.error("Lỗi lấy StudyProgramID: %s", e)
            raise Exception(f"Lấy StudyProgramID thất bại: {e}")

    def _find_course_metadata_safe(self, data: list, raw_course_id: str) -> Optional[dict]:
        clean_id = str(raw_course_id).strip().upper()
        for item in data:
            if isinstance(item, dict):
                curr_id = str(item.get("CurriculumID", "")).strip().upper()
                alias_id = str(item.get("ScheduleStudyUnitAlias", "")).strip().upper()
                if clean_id == curr_id or clean_id == alias_id:
                    return item
        return None

    async def fetch_course_metadata(self, jwt_token: str, course_ids: List[str], study_program_id: str, regist_type: str) -> None:
        """Fetch and cache course metadata by CurriculumID for requested courses."""
        import json
        headers = self._build_shared_headers(jwt_token)
        for course_id in course_ids:
            clean_id = str(course_id).strip().upper()
            base_id = clean_id.split("_", 1)[0]
            payload = {
                "ReqParam1": study_program_id,
                "ReqParam2": regist_type,
                "ReqParam3": base_id,
            }
            logger.info("🔍 [DEBUG] Sending payload: ReqParam3='%s' (Original: '%s')", base_id, course_id)
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

                match = self._find_course_metadata_safe(data, course_id)
                if match is None:
                    logger.error("🚨 FAILED TO MATCH COURSE: '%s' (Length: %d)", course_id, len(course_id))
                    logger.error("📦 Số lượng lớp học server nhả về: %d", len(data))
                    if data:
                        logger.error("X-QUANG PHẦN TỬ ĐẦU TIÊN:\n%s", json.dumps(data[0], indent=2, ensure_ascii=False))
                        
                        logger.error("--- DANH SÁCH CÁC MÔN SERVER TRẢ VỀ ---")
                        for idx, item in enumerate(data):
                            if isinstance(item, dict):
                                curr_id = item.get("CurriculumID", "None")
                                alias_id = item.get("ScheduleStudyUnitAlias", "None")
                                logger.error(" [%d] CurriculumID: '%s' | Alias: '%s'", idx, curr_id, alias_id)
                    continue

                async with self.cache_lock:
                    self.course_cache[course_id] = match
                logger.info("Đã tải xong metadata cho môn: %s", course_id)
            except Exception as e:
                logger.error("Lỗi tải metadata cho môn %s: %s", course_id, e)

    async def is_slot_available(self, jwt_token: str, course_id: str, study_program_id: str, regist_type: str) -> bool:
        headers = self._build_shared_headers(jwt_token)
        clean_id = str(course_id).strip().upper()
        base_id = clean_id.split("_", 1)[0]
        payload = {
            "ReqParam1": study_program_id,
            "ReqParam2": regist_type,
            "ReqParam3": base_id,
        }
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
                return False
            match = self._find_course_metadata_safe(data, course_id)
            if match is not None:
                async with self.cache_lock:
                    self.course_cache[course_id] = match
            if match is None:
                return False
            return int(match.get("NumberOfStudents", 0)) < int(match.get("MaxStudentNumber", 1))
        except Exception as e:
            logger.error("Lỗi khi check slot môn %s: %s", course_id, e)
            raise

    async def register_course(
        self,
        curriculum_ids: list[str],
        study_program_id: str,
        regist_type: str,
        jwt_token: str,
        refresh_jwt_token: Optional[Callable[[], Awaitable[str]]] = None,
    ) -> Dict[str, Any]:
        self.success_flag.clear()
        self.result = None
        self.last_result_detail = {}

        params = {
            "TurnID": "139",
            "Action": "REGIST",
            "StudyProgramID": study_program_id,
            "RegistType": regist_type,
        }
        headers = self._build_shared_headers(jwt_token)

        async with self.cache_lock:
            cache_snapshot = self.course_cache.copy()

        last_detail: Dict[str, Any] = {
            "success": False,
            "status_code": None,
            "message": "Không có course_id hợp lệ để gửi",
        }
        max_attempts = max(1, self.max_attempts_per_job or 5)

        for course_id in curriculum_ids:
            if self.success_flag.is_set():
                break
            cached_obj = cache_snapshot.get(course_id)
            if not isinstance(cached_obj, dict):
                logger.warning("Cache rỗng cho môn %s. Bot đang tự động đi lấy metadata...", course_id)
                await self.fetch_course_metadata(jwt_token, [course_id], study_program_id, regist_type)
                
                # Đọc lại cache snapshot sau khi lấy xong
                async with self.cache_lock:
                    cache_snapshot = self.course_cache.copy()
                cached_obj = cache_snapshot.get(course_id)
                
                # Nếu vẫn không có, lúc này mới thực sự bỏ cuộc
                if not isinstance(cached_obj, dict):
                    logger.error("Lỗi: Không tìm thấy lớp %s dù đã cố fetch lại", course_id)
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

            async def _fire_request() -> Dict[str, Any]:
                if self.success_flag.is_set():
                    raise RuntimeError("Skipped because success_flag already set")

                response = await self.client.post(
                    "https://tinchi-api.neu.edu.vn/api/Regist/RegistScheduleStudyUnit",
                    params=params,
                    json=[payload_obj],
                    headers=headers,
                    timeout=3.0,
                )
                print(f"🚀 Request thành công tới URL: {response.request.url}")

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

                detail = {
                    "success": response.status_code == 200,
                    "status_code": response.status_code,
                    "message": parsed_message or response_text or "No response body",
                }

                if response.status_code == 200:
                    return detail

                if response.status_code in (400, 401, 403, 409):
                    raise httpx.HTTPStatusError(
                        f"Fatal response {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server overload {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                return detail

            config = RetryConfig(max_retries=10, base_delay_ms=100, max_delay_ms=500)
            try:
                result = await RetryManager.execute_with_retry(
                    coro_fn=_fire_request,
                    config=config,
                    on_retry=lambda idx, err: logger.warning(
                        "Server quá tải, đang thử lại lần %s... (%s)",
                        idx,
                        err,
                    ),
                )
                last_detail = result
                if result.get("success"):
                    self.result = True
                    self.success_flag.set()
                    logger.info("Đăng ký thành công")
                    return result
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code if e.response is not None else None
                response_text = e.response.text if e.response is not None else str(e)
                logger.error("Lỗi fatal %s cho %s, dừng retry.", status_code, course_id)
                last_detail = {
                    "success": False,
                    "status_code": status_code,
                    "message": response_text,
                }
            except Exception as e:
                logger.exception("Request attempt failed for %s: %s", course_id, e)
                last_detail = {
                    "success": False,
                    "status_code": None,
                    "message": str(e),
                }

        return last_detail

    async def multi_course_register(
        self,
        course_ids: list[str],
        study_program_id: str,
        regist_type: str,
        jwt_token: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Register multiple courses concurrently."""
        tasks = [
            self.register_course(
                curriculum_ids=[course_id],
                study_program_id=study_program_id,
                regist_type=regist_type,
                jwt_token=jwt_token,
            )
            for course_id in course_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_results = {}
        for course_id, result in zip(course_ids, results):
            if isinstance(result, Exception):
                final_results[course_id] = {
                    "success": False,
                    "status_code": None,
                    "message": str(result)
                }
            else:
                final_results[course_id] = result
        return final_results


class FastScheduler:
    @staticmethod
    async def wait_until(target_timestamp: float, offset_ms: int = 0) -> None:
        """High-precision wait using PrecisionScheduler."""
        from worker.scheduler import PrecisionScheduler
        await PrecisionScheduler.wait_until(target_timestamp, offset_ms)


