"""
Core security primitives for NammaClean.
Handles password hashing and verification using Argon2id via pwdlib.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from jwt.exceptions import PyJWTError, ExpiredSignatureError, InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

# Initialize Argon2id password hasher
# Argon2id provides memory-hardness and protection against GPU/ASIC cracking
_password_hasher = PasswordHash((Argon2Hasher(),))


def hash_password(plain_password: str) -> str:
    """
    Hashes a plaintext password using Argon2id with automatic salt generation.
    Raises ValueError if plain_password is empty.
    """
    if not plain_password or not plain_password.strip():
        raise ValueError("Password cannot be empty or contain only whitespace.")
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plaintext password against an Argon2id hash in constant time.
    Returns False safely if either input is empty, None, or if the hash is malformed.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return _password_hasher.verify(plain_password, hashed_password)
    except Exception:
        # Handles malformed hash strings or corrupted data safely without crashing
        return False


def get_jwt_secret_key() -> str:
    """
    Validates and retrieves the JWT secret key from application settings.
    Ensures the secret is present, not a placeholder, and meets the minimum
    cryptographic length of 32 characters for HS256 security.
    Raises ValueError if the secret key is invalid.
    """
    secret = settings.JWT_SECRET_KEY.strip()
    if not secret:
        raise ValueError("JWT_SECRET_KEY is not configured in environment settings.")
    if len(secret) < 32:
        raise ValueError("JWT_SECRET_KEY is too short: must be at least 32 characters long for HS256.")
    if "change_me" in secret.lower() or "placeholder" in secret.lower() or "secret" == secret.lower():
        raise ValueError("Insecure JWT_SECRET_KEY: please set a strong random secret in .env.")
    return secret


def validate_jwt_algorithm() -> str:
    """
    Validates and retrieves the JWT signing algorithm from application settings.
    Ensures only supported algorithms (HS256) are permitted.
    """
    algo = settings.JWT_ALGORITHM
    if algo != "HS256":
        raise ValueError(f"Unsupported JWT algorithm: '{algo}'. Only 'HS256' is permitted.")
    return algo


def create_access_token(
    subject: str | uuid.UUID,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Creates a signed HS256 JWT access token.

    Claims:
    - sub: string representation of user UUID
    - iat: UTC timestamp when issued
    - exp: UTC expiration timestamp
    - jti: unique token identifier (UUID v4)
    - optional extra claims (e.g. role)

    Raises ValueError if subject is not a valid UUID or UUID string.
    """
    if subject is None:
        raise ValueError("Token subject cannot be None.")

    try:
        subject_str = str(subject).strip()
        if not subject_str:
            raise ValueError("Token subject cannot be empty.")
        # Enforce that subject represents a valid UUID
        parsed_uuid = uuid.UUID(subject_str)
        valid_sub = str(parsed_uuid)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Token subject must be a valid UUID or UUID string: {exc}") from exc

    secret_key = get_jwt_secret_key()
    algorithm = validate_jwt_algorithm()

    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        if expires_delta.total_seconds() <= 0:
            raise ValueError("Token expiration delta must be positive.")
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": valid_sub,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
    }

    if extra_claims:
        # Prevent collision/overwriting of core security claims
        reserved_claims = {"sub", "iat", "exp", "jti"}
        for key, value in extra_claims.items():
            if key not in reserved_claims:
                payload[key] = value

    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and strictly verifies an HS256 JWT access token.

    Validates:
    - Signature using validated secret key
    - Algorithm strictly pinned to HS256 (preventing algorithm confusion or 'none' attacks)
    - Expiration (exp)
    - Token structure and required claims ('sub', 'iat', 'exp', 'jti')
    - Subject ('sub') format as a valid UUID string
    - 'jti' format as a non-empty string and valid UUID

    Returns decoded claims dictionary.
    Raises:
    - ExpiredSignatureError: if token has expired
    - InvalidTokenError: if signature is invalid, algorithm mismatched, required claims missing, or claims malformed
    - ValueError: if token string is empty
    """
    if not token or not token.strip():
        raise ValueError("Token string cannot be empty.")

    secret_key = get_jwt_secret_key()
    algorithm = validate_jwt_algorithm()

    # algorithms=[algorithm] strictly rejects tokens signed with different algorithms
    payload = jwt.decode(
        token.strip(),
        secret_key,
        algorithms=[algorithm],
        options={
            "require": ["sub", "iat", "exp", "jti"],
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": True,
        },
    )

    # Validate 'sub' claim is a valid UUID string
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise InvalidTokenError("Token subject ('sub') must be a non-empty string.")
    try:
        uuid.UUID(sub.strip())
    except (ValueError, TypeError, AttributeError):
        raise InvalidTokenError("Token subject ('sub') must be a valid UUID string.")

    # Validate 'jti' claim is a non-empty string and valid UUID
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti.strip():
        raise InvalidTokenError("Token identifier ('jti') must be a non-empty string.")
    try:
        uuid.UUID(jti.strip())
    except (ValueError, TypeError, AttributeError):
        raise InvalidTokenError("Token identifier ('jti') must be a valid UUID string.")

    return payload


