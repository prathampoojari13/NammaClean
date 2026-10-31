"""
Pydantic schemas for user and registration workflows.
"""

import re
from datetime import datetime
import uuid
from typing import Optional
from pydantic import BaseModel, Field, SecretStr, ConfigDict, field_validator

from app.models.user import normalize_email
from app.models.enums import UserRole, UserStatus


# RFC 5322-compliant basic email validation pattern that does not require external libraries
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class UserRegisterRequest(BaseModel):
    """
    Client registration schema for public citizen account creation.
    Privileged fields (role, status, password_hash, id) are strictly forbidden
    via extra='forbid'.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    email: str = Field(
        ...,
        max_length=255,
        description="Valid email address for citizen account.",
    )
    password: SecretStr = Field(
        ...,
        description="Password meeting minimum security length requirements (12 to 128 characters).",
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
    def validate_password_length(cls, v: SecretStr) -> SecretStr:
        val = v.get_secret_value()
        if len(val) < 12:
            raise ValueError("Password must be at least 12 characters long.")
        if len(val) > 128:
            raise ValueError("Password must not exceed 128 characters.")
        return v


class UserResponse(BaseModel):
    """
    Public representation of a user account.
    Excludes password_hash and internal credentials.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    status: str
    created_at: datetime
    updated_at: datetime


class AdminUserCreateRequest(BaseModel):
    """
    Administrator schema for creating operational personnel accounts.
    Restricted to Municipal Admins.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    email: str = Field(
        ...,
        max_length=255,
        description="Valid email address for operational personnel account.",
    )
    password: SecretStr = Field(
        ...,
        description="Password meeting minimum security length requirements (12 to 128 characters).",
    )
    role: UserRole = Field(
        ...,
        description="Operational role (SANITATION_WORKER, DRIVER, WARD_SUPERVISOR).",
    )
    status: UserStatus = Field(
        default=UserStatus.ACTIVE,
        description="Initial operational account status.",
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
    def validate_password_length(cls, v: SecretStr) -> SecretStr:
        val = v.get_secret_value()
        if len(val) < 12:
            raise ValueError("Password must be at least 12 characters long.")
        if len(val) > 128:
            raise ValueError("Password must not exceed 128 characters.")
        return v


class UserWardAssignmentResponse(BaseModel):
    """
    Representation of an administrative or operational ward assignment.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    ward_id: uuid.UUID
    assigned_at: datetime
    revoked_at: Optional[datetime] = None

