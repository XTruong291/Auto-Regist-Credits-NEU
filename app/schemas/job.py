from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional
from datetime import datetime


class JobSubmitRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    regist_type: str = Field(default="NKH")
    course_ids: List[str] = Field(..., min_items=1, max_items=50)
    target_timestamp: float = Field(..., gt=0)

    @validator("course_ids", each_item=True)
    def validate_course_id(cls, v):
        if not v or len(v) > 50:
            raise ValueError("Invalid course ID format")
        return v


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: Dict[str, str] = {}
    error: Optional[str] = None
    created_at: str


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str
    created_at: str


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    version: str
