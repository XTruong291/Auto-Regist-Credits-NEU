from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
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


@app.get("/utils/time")
async def get_time_utils():
    """Helper endpoint for quickly obtaining useful Unix timestamps."""
    now = datetime.utcnow()
    plus_1_min = now + timedelta(minutes=1)
    plus_5_min = now + timedelta(minutes=5)
    return {
        "now_iso_utc": now.isoformat(),
        "now_timestamp": now.timestamp(),
        "plus_1_min_timestamp": plus_1_min.timestamp(),
        "plus_5_min_timestamp": plus_5_min.timestamp(),
    }


@app.post("/jobs", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(request: JobSubmitRequest):
    """
    Submit course registration job.
    
    - **jwt_token**: JWT token copied from browser
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
            jwt_token=request.jwt_token,
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
