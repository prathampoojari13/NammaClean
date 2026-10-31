"""
Pydantic schemas for authentication and token responses.
"""

import re
from pydantic import BaseModel, Field, SecretStr, ConfigDict, field_validator

from app.models.user import normalize_email

# RFC 5322-compliant basic email validation pattern that does not require external libraries
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class LoginRequest(BaseModel):
    """
    Client credentials schema for user authentication.
    Unexpected fields are strictly forbidden via extra='forbid'.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    email: str = Field(
        ...,
        max_length=255,
        description="Registered user email address.",
    )
    password: SecretStr = Field(
        ...,
        description="Plaintext password to authenticate.",
    )

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Email address cannot be empty or contain only whitespace.")
        normalized = normalize_email(v)
        if not EMAIL_REGEX.match(normalized):
            raise ValueError("Invalid email address format.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, v: SecretStr) -> SecretStr:
        val = v.get_secret_value()
        if not val or not val.strip():
            raise ValueError("Password cannot be empty or contain only whitespace.")
        return v


class TokenResponse(BaseModel):
    """
    Public token payload returned upon successful authentication.
    """
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(
        ...,
        description="Signed HS256 JWT access token.",
    )
    token_type: str = Field(
        default="bearer",
        description="Token authorization scheme.",
    )
