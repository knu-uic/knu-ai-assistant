from pydantic import BaseModel, Field


class SignupCodeRequest(BaseModel):
    email: str = Field(max_length=100)


class SignupVerifyRequest(BaseModel):
    email: str = Field(max_length=100)
    code: str = Field(min_length=6, max_length=6)
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class PortalLoginRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
