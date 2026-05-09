from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, timezone
import logging
import asyncio
from contextlib import asynccontextmanager

from config import AppConfig, get_logger
from app.schemas.job import JobSubmitRequest, JobStatusResponse, JobSubmitResponse, HealthCheckResponse
from worker.main import WorkerPool

logger = get_logger(__name__)
worker_pool: WorkerPool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global worker_pool
    logger.info("Initializing worker pool...")
    worker_pool = WorkerPool(num_workers=AppConfig.WORKER_CONFIG.NUM_WORKERS)
    logger.info(f"Worker pool initialized with {AppConfig.WORKER_CONFIG.NUM_WORKERS} workers")
    logger.info("--- Worker đã bắt đầu lắng nghe Queue ---")
    yield
    logger.info("Shutting down worker pool...")
    await worker_pool.shutdown()
    logger.info("Worker pool shutdown complete")


app = FastAPI(
    title=AppConfig.API_TITLE,
    version=AppConfig.API_VERSION,
    lifespan=lifespan,
)

@app.get("/")
async def root():
    return {"message": "running"}

@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": AppConfig.API_VERSION,
    }


@app.get("/utils/generate-timestamp")
async def generate_timestamp(
    target_str: str = Query(..., description='Thời gian mở cổng theo giờ VN (Ví dụ: "2026-05-10 08:00:00")'),
    drift_seconds: float = Query(-30.361, description='Độ lệch đồng hồ Server NEU')
):
    """Sniper Calculator - Công cụ tính toán thời gian nổ súng chuyên dụng cho server NEU."""
    logger.info(f"Sniper Calculator: Tính timestamp cho mục tiêu '{target_str}' với độ lệch {drift_seconds}s")
    try:
        dt_vnt = datetime.strptime(target_str, "%Y-%m-%d %H:%M:%S")
        dt_utc = dt_vnt - timedelta(hours=7)
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        base_timestamp = dt_utc.timestamp()
        final_timestamp = base_timestamp - drift_seconds

        return {
            "1_target_vnt": dt_vnt.isoformat(),
            "2_target_utc": dt_utc.isoformat(),
            "3_drift_applied": drift_seconds,
            "4_FINAL_TIMESTAMP": final_timestamp,
            "instruction": "Copy dãy số 4_FINAL_TIMESTAMP và dán vào tham số target_timestamp của API tạo Job."
        }
    except ValueError:
        logger.error(f"Sniper Calculator: Đầu vào sai định dạng '{target_str}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sai định dạng thời gian. Vui lòng nhập chuẩn theo mẫu: YYYY-MM-DD HH:MM:SS"
        )


@app.post("/jobs", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(request: JobSubmitRequest):
    """
    Submit course registration job.
    
    - **username**: Tài khoản sinh viên
    - **password**: Mật khẩu sinh viên
    - **regist_type**: Loại đăng ký (NKH,...)
    - **course_ids**: List of course IDs to register
    - **target_timestamp**: Unix timestamp for registration attempt
    """
    try:
        if worker_pool is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Worker pool not initialized"
            )

        job_id = await worker_pool.submit_job(
            username=request.username,
            password=request.password,
            regist_type=request.regist_type,
            course_ids=request.course_ids,
            target_timestamp=request.target_timestamp,
        )

        return {
            "job_id": job_id,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.exception(f"Error submitting job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit job"
        )


@app.get("/jobs", response_model=list[dict])
async def get_all_jobs():
    """
    Giám sát trạng thái toàn bộ Jobs.
    """
    if worker_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker pool not initialized"
        )
    return worker_pool.get_all_jobs_status()


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """
    Hủy Job đang chạy.
    """
    if worker_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker pool not initialized"
        )
    success = worker_pool.cancel_job(job_id)
    if success:
        return {"message": "Hủy thành công"}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Không tìm thấy job"
    )


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get job status and results.
    
    - **job_id**: Job ID returned from POST /jobs
    """
    try:
        if worker_pool is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Worker pool not initialized"
            )

        status_data = await worker_pool.get_job_status(job_id)
        if not status_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found"
            )

        return status_data

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting job status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve job status"
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=AppConfig.UVICORN_HOST,
        port=AppConfig.UVICORN_PORT,
        workers=AppConfig.UVICORN_WORKERS,
        reload=AppConfig.UVICORN_RELOAD,
        log_level=AppConfig.LOG_LEVEL.lower(),
    )
