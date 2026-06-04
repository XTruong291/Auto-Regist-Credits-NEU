import logging
import os
from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Optional, List


class EnvironmentEnum(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    STAGING = "staging"


class BaseConfig:
    """Base configuration."""
    ENV: EnvironmentEnum = EnvironmentEnum(os.getenv("ENV", EnvironmentEnum.PRODUCTION.value))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    API_TITLE: str = "Course Registration Bot"
    API_VERSION: str = "1.0.0"


class WorkerConfig:
    """Worker configuration."""
    NUM_WORKERS: int = int(os.getenv("NUM_WORKERS", "4"))
    MAX_CONNECTIONS: int = int(os.getenv("MAX_CONNECTIONS", "200"))
    MAX_KEEPALIVE_CONNECTIONS: int = int(os.getenv("MAX_KEEPALIVE_CONNECTIONS", "100"))
    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "3.0"))
    SCAN_INTERVAL_MIN_SECONDS: float = float(os.getenv("SCAN_INTERVAL_MIN_SECONDS", "1.0"))
    SCAN_INTERVAL_MAX_SECONDS: float = float(os.getenv("SCAN_INTERVAL_MAX_SECONDS", "2.5"))
    JOB_TIMEOUT_SECONDS: int = int(os.getenv("JOB_TIMEOUT_SECONDS", str(7 * 24 * 3600)))


class AppConfig(BaseConfig):
    """Application configuration."""
    WORKER_CONFIG = WorkerConfig()
    UVICORN_HOST: str = os.getenv("UVICORN_HOST", "0.0.0.0")
    UVICORN_PORT: int = int(os.getenv("UVICORN_PORT", "8000"))
    UVICORN_WORKERS: int = int(os.getenv("UVICORN_WORKERS", "1"))
    UVICORN_RELOAD: bool = os.getenv("UVICORN_RELOAD", "false").lower() == "true"

    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+psycopg://neu_bot:neu_bot@postgres:5432/neu_bot")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")


def get_logger(name: str) -> logging.Logger:
    """Get configured logger."""
    logger = logging.getLogger(name)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(AppConfig.LOG_LEVEL)
    return logger
