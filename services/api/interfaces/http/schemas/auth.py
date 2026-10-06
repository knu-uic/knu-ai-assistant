"""Authentication transport schemas."""

from pydantic import BaseModel, Field


class PortalLoginRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
