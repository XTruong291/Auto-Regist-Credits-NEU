from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import (
    JobEvent,
    NeuAccount,
    RegistrationJob,
    SessionLocal,
    get_account_by_neu_token,
    hash_token,
    init_db,
    utc_now,
)
from app.schemas.job import (
    HealthCheckResponse,
    JobEventResponse,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
    NeuLoginRequest,
    NeuLoginResponse,
)
from config import AppConfig, EnvironmentEnum, get_logger
from worker.engine import RequestEngine
from worker.tasks import run_registration_job

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("Database ready")
    yield


app = FastAPI(
    title=AppConfig.API_TITLE,
    version=AppConfig.API_VERSION,
    lifespan=lifespan,
    docs_url=None if AppConfig.ENV == EnvironmentEnum.PRODUCTION else "/docs",
    redoc_url=None if AppConfig.ENV == EnvironmentEnum.PRODUCTION else "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=AppConfig.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


def _extract_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    if credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")
    return credentials.credentials


async def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db_session),
) -> NeuAccount:
    token = _extract_bearer_token(credentials)
    account = get_account_by_neu_token(db, token)
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid NEU token")
    return account


def _job_response(job: RegistrationJob) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "result": job.result or {},
        "error": job.error,
        "course_ids": job.course_ids or [],
        "target_timestamp": job.target_timestamp,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _event_response(event: JobEvent) -> dict:
    return {
        "event_id": event.id,
        "job_id": event.job_id,
        "event_type": event.event_type,
        "message": event.message,
        "metadata": event.metadata_json or {},
        "created_at": event.created_at.isoformat(),
    }


@app.get("/")
async def root():
    return {"message": "running"}


@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    return {
        "status": "healthy",
        "timestamp": utc_now().isoformat(),
        "version": AppConfig.API_VERSION,
    }


@app.get("/utils/generate-timestamp")
async def generate_timestamp(
    target_str: str = Query(..., description='Thời gian mở cổng theo giờ VN (Ví dụ: "2026-05-10 08:00:00")'),
    drift_seconds: float = Query(-30.361, description="Độ lệch đồng hồ Server NEU"),
):
    logger.info("Sniper Calculator: target=%s drift=%s", target_str, drift_seconds)
    try:
        dt_vnt = datetime.strptime(target_str, "%Y-%m-%d %H:%M:%S")
        dt_utc = (dt_vnt - timedelta(hours=7)).replace(tzinfo=timezone.utc)
        base_timestamp = dt_utc.timestamp()
        final_timestamp = base_timestamp - drift_seconds

        return {
            "1_target_vnt": dt_vnt.isoformat(),
            "2_target_utc": dt_utc.isoformat(),
            "3_drift_applied": drift_seconds,
            "4_FINAL_TIMESTAMP": final_timestamp,
            "instruction": "Copy 4_FINAL_TIMESTAMP và dùng làm target_timestamp khi tạo job.",
        }
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sai định dạng thời gian. Vui lòng nhập chuẩn: YYYY-MM-DD HH:MM:SS",
        )


@app.post("/auth/neu/login", response_model=NeuLoginResponse)
async def neu_login(request: NeuLoginRequest, db: Session = Depends(get_db_session)):
    async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
        engine = RequestEngine(client)
        try:
            neu_token = await engine.authenticate(request.neu_username, request.neu_password)
        except Exception as exc:
            logger.warning("NEU login failed for username=%s", request.neu_username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"NEU login failed: {exc}",
            )

    account = db.execute(
        select(NeuAccount).where(NeuAccount.neu_username == request.neu_username)
    ).scalar_one_or_none()
    now = utc_now()
    if account is None:
        account = NeuAccount(
            neu_username=request.neu_username,
            neu_password=request.neu_password,
            neu_token_hash=hash_token(neu_token),
            last_login_at=now,
        )
        db.add(account)
    else:
        account.neu_password = request.neu_password
        account.neu_token_hash = hash_token(neu_token)
        account.last_login_at = now
        account.updated_at = now
    db.commit()
    db.refresh(account)

    return {
        "neu_token": neu_token,
        "token_type": "Bearer",
        "neu_username": account.neu_username,
    }


@app.post("/jobs", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(
    request: JobSubmitRequest,
    account: NeuAccount = Depends(get_current_account),
    db: Session = Depends(get_db_session),
):
    job = RegistrationJob(
        neu_account_id=account.id,
        regist_type=request.regist_type,
        course_ids=request.course_ids,
        target_timestamp=request.target_timestamp,
        status="QUEUED",
        result={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    run_registration_job.delay(job.id)
    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
    }


@app.get("/jobs", response_model=list[JobStatusResponse])
async def get_all_jobs(
    account: NeuAccount = Depends(get_current_account),
    db: Session = Depends(get_db_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = (
        select(RegistrationJob)
        .where(RegistrationJob.neu_account_id == account.id)
        .order_by(RegistrationJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_job_response(job) for job in db.execute(stmt).scalars().all()]


@app.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    account: NeuAccount = Depends(get_current_account),
    db: Session = Depends(get_db_session),
):
    job = db.get(RegistrationJob, job_id)
    if job is None or job.neu_account_id != account.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy job")
    job.cancel_requested = True
    if job.status in {"QUEUED", "CAMPING", "RUNNING"}:
        job.status = "CANCELLED"
    job.updated_at = utc_now()
    db.commit()
    return {"message": "Hủy thành công"}


@app.get("/jobs/{job_id}/events", response_model=list[JobEventResponse])
async def get_job_events(
    job_id: str,
    account: NeuAccount = Depends(get_current_account),
    db: Session = Depends(get_db_session),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    job = db.get(RegistrationJob, job_id)
    if job is None or job.neu_account_id != account.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")

    stmt = (
        select(JobEvent)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return [_event_response(event) for event in db.execute(stmt).scalars().all()]


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    account: NeuAccount = Depends(get_current_account),
    db: Session = Depends(get_db_session),
):
    job = db.get(RegistrationJob, job_id)
    if job is None or job.neu_account_id != account.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")
    return _job_response(job)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=AppConfig.UVICORN_HOST,
        port=AppConfig.UVICORN_PORT,
        workers=AppConfig.UVICORN_WORKERS,
        reload=AppConfig.UVICORN_RELOAD,
        log_level=AppConfig.LOG_LEVEL.lower(),
    )
