from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Optional


class NeuLoginRequest(BaseModel):
    neu_username: str = Field(..., min_length=1, max_length=100)
    neu_password: str = Field(..., min_length=1)


class NeuLoginResponse(BaseModel):
    neu_token: str
    token_type: str = "Bearer"
    neu_username: str


class JobSubmitRequest(BaseModel):
    regist_type: str = Field(default="NKH", max_length=50)
    course_ids: List[str] = Field(..., min_length=1, max_length=50)
    target_timestamp: float = Field(..., gt=0)

    @field_validator("course_ids")
    @classmethod
    def validate_course_ids(cls, value: List[str]) -> List[str]:
        cleaned = []
        for course_id in value:
            course_id = str(course_id).strip()
            if not course_id or len(course_id) > 50:
                raise ValueError("Invalid course ID format")
            cleaned.append(course_id)
        return cleaned


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: Dict[str, Any] = {}
    error: Optional[str] = None
    course_ids: List[str] = []
    target_timestamp: float
    created_at: str
    updated_at: str


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str = "QUEUED"
    created_at: str


class JobEventResponse(BaseModel):
    event_id: str
    job_id: str
    event_type: str
    message: str
    metadata: Dict[str, Any] = {}
    created_at: str


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    version: str
