import logging
from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Optional, List


class EnvironmentEnum(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    STAGING = "staging"


class BaseConfig:
    """Base configuration."""
    ENV: EnvironmentEnum = EnvironmentEnum.PRODUCTION
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    API_TITLE: str = "Course Registration Bot"
    API_VERSION: str = "1.0.0"


class WorkerConfig:
    """Worker configuration."""
    NUM_WORKERS: int = 4
    MAX_CONNECTIONS: int = 200
    MAX_KEEPALIVE_CONNECTIONS: int = 100
    REQUEST_TIMEOUT_SECONDS: float = 3.0
    NUM_BURSTS: int = 4
    BURST_DELAY_MS: int = 150
    REQUESTS_PER_BURST: int = 120
    SEMAPHORE_LIMIT: int = 120


class AppConfig(BaseConfig):
    """Application configuration."""
    WORKER_CONFIG = WorkerConfig()
    UVICORN_HOST: str = "0.0.0.0"
    UVICORN_PORT: int = 8000
    UVICORN_WORKERS: int = 1
    UVICORN_RELOAD: bool = False


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
