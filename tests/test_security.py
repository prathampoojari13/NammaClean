import pytest
from app.core.security import (
    hash_password,
    verify_password,
    get_jwt_secret_key,
    validate_jwt_algorithm,
)
from app.core.config import settings


def test_password_is_hashed_not_plaintext():
    """Verify that password hashing converts plaintext into an Argon2id hash."""
    plain_password = "SuperSecretPassword123!"
    hashed = hash_password(plain_password)

    # Must not store plaintext
    assert hashed != plain_password
    assert plain_password not in hashed

    # Must use Argon2id format
    assert hashed.startswith("$argon2id$")
    assert len(hashed) > 50


def test_hashing_same_password_produces_unique_salted_hashes():
    """Verify that hashing the same password twice yields distinct hashes due to random salting."""
    plain_password = "BangaloreWasteManagement2026"
    hash_one = hash_password(plain_password)
    hash_two = hash_password(plain_password)

    assert hash_one != hash_two
    # Both must still verify against the original plaintext
    assert verify_password(plain_password, hash_one) is True
    assert verify_password(plain_password, hash_two) is True


def test_correct_password_verifies_successfully():
    """Verify that the correct plaintext password validates against its hash."""
    plain_password = "CorrectHorseBatteryStaple"
    hashed = hash_password(plain_password)
    assert verify_password(plain_password, hashed) is True


def test_incorrect_password_fails_verification():
    """Verify that an incorrect plaintext password fails verification."""
    plain_password = "CorrectPassword123"
    hashed = hash_password(plain_password)

    assert verify_password("WrongPassword123", hashed) is False
    assert verify_password("correctpassword123", hashed) is False  # Case-sensitive check
    assert verify_password("", hashed) is False
    assert verify_password(plain_password, "") is False


def test_malformed_hash_fails_gracefully():
    """Verify that corrupted or malformed hash strings fail verification safely without raising unhandled exceptions."""
    assert verify_password("ValidPassword123", "corrupted_non_argon_hash") is False
    assert verify_password("ValidPassword123", "$argon2id$invalid_payload") is False


def test_empty_password_hashing_raises_value_error():
    """Verify that empty or whitespace-only passwords cannot be hashed."""
    with pytest.raises(ValueError, match="Password cannot be empty"):
        hash_password("")

    with pytest.raises(ValueError, match="Password cannot be empty"):
        hash_password("   ")


def test_valid_jwt_security_configuration():
    """Verify that valid JWT configuration is retrieved and supported algorithm is verified."""
    secret = get_jwt_secret_key()
    assert isinstance(secret, str)
    assert len(secret) >= 32

    algo = validate_jwt_algorithm()
    assert algo == "HS256"


def test_missing_or_insecure_jwt_secret_raises_error(monkeypatch):
    """Verify that missing, short, or placeholder JWT secret keys raise explicit ValueError."""
    # Empty secret
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY is not configured"):
        get_jwt_secret_key()

    # Whitespace-only secret
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "    ")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY is not configured"):
        get_jwt_secret_key()

    # Short secret (< 32 chars)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "short_secret_under_32_chars!")
    with pytest.raises(ValueError, match="too short"):
        get_jwt_secret_key()

    # Placeholder secret
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "change_me_to_a_secure_random_secret_at_least_32_chars")
    with pytest.raises(ValueError, match="Insecure JWT_SECRET_KEY"):
        get_jwt_secret_key()

    # Obvious placeholder 'placeholder'
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "placeholder_secret_value_that_is_32_chars_long")
    with pytest.raises(ValueError, match="Insecure JWT_SECRET_KEY"):
        get_jwt_secret_key()


def test_unsupported_jwt_algorithm_raises_error(monkeypatch):
    """Verify that attempting to configure an unsupported JWT algorithm raises ValueError."""
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "none")

    with pytest.raises(ValueError, match="Unsupported JWT algorithm"):
        validate_jwt_algorithm()


def test_access_token_expire_minutes_default():
    """Verify that the default access-token expiry is 30 minutes."""
    from app.core.config import Settings
    custom_settings = Settings(_env_file=None)
    assert custom_settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30


def test_access_token_expire_minutes_accepts_valid_range():
    """Verify that positive values within [1, 10080] are accepted."""
    from app.core.config import Settings
    s1 = Settings(_env_file=None, ACCESS_TOKEN_EXPIRE_MINUTES=1)
    assert s1.ACCESS_TOKEN_EXPIRE_MINUTES == 1

    s60 = Settings(_env_file=None, ACCESS_TOKEN_EXPIRE_MINUTES=60)
    assert s60.ACCESS_TOKEN_EXPIRE_MINUTES == 60

    s_max = Settings(_env_file=None, ACCESS_TOKEN_EXPIRE_MINUTES=10080)
    assert s_max.ACCESS_TOKEN_EXPIRE_MINUTES == 10080


def test_access_token_expire_minutes_rejects_zero():
    """Verify that an expiry of zero minutes is rejected."""
    from pydantic import ValidationError
    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ACCESS_TOKEN_EXPIRE_MINUTES=0)


def test_access_token_expire_minutes_rejects_negative():
    """Verify that negative expiry values are rejected."""
    from pydantic import ValidationError
    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ACCESS_TOKEN_EXPIRE_MINUTES=-15)


def test_access_token_expire_minutes_rejects_exceeding_max():
    """Verify that expiry values exceeding 10080 minutes (7 days) are rejected."""
    from pydantic import ValidationError
    from app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ACCESS_TOKEN_EXPIRE_MINUTES=10081)


# --- JWT Token Generation & Verification Tests ---

def test_create_and_decode_access_token_success():
    """Verify that an access token is created and decoded successfully with valid claims."""
    import uuid
    from app.core.security import create_access_token, decode_access_token

    test_user_id = uuid.uuid4()
    token = create_access_token(
        subject=test_user_id,
        extra_claims={"role": "CITIZEN", "email": "citizen@example.com"},
    )
    assert isinstance(token, str)
    assert len(token.split(".")) == 3  # Standard header.payload.signature

    claims = decode_access_token(token)
    assert claims["sub"] == str(test_user_id)
    assert claims["role"] == "CITIZEN"
    assert claims["email"] == "citizen@example.com"
    assert "iat" in claims
    assert "exp" in claims
    assert "jti" in claims
    # JTI must be a valid UUID string
    assert uuid.UUID(claims["jti"])


def test_token_expiration_verified():
    """Verify that expired tokens are strictly rejected with ExpiredSignatureError."""
    import uuid
    from datetime import timedelta
    from jwt.exceptions import ExpiredSignatureError
    from app.core.security import create_access_token, decode_access_token

    test_user_id = uuid.uuid4()
    # Create token already expired 10 seconds ago
    token = create_access_token(
        subject=test_user_id,
        expires_delta=timedelta(seconds=-10),  # Will be tested directly via negative delta check
    ) if False else None

    # Verify negative timedelta in create_access_token is rejected
    with pytest.raises(ValueError, match="Token expiration delta must be positive"):
        create_access_token(subject=test_user_id, expires_delta=timedelta(seconds=-1))

    # Manually encode an expired token using valid secret to verify decode_access_token catches it
    import jwt
    from app.core.security import get_jwt_secret_key, validate_jwt_algorithm
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": str(test_user_id),
        "iat": int((now - timedelta(minutes=10)).timestamp()),
        "exp": int((now - timedelta(minutes=5)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    expired_token = jwt.encode(expired_payload, get_jwt_secret_key(), algorithm=validate_jwt_algorithm())

    with pytest.raises(ExpiredSignatureError):
        decode_access_token(expired_token)


def test_token_with_invalid_signature_fails():
    """Verify that tokens signed with a different key fail verification."""
    import uuid
    import jwt
    from jwt.exceptions import InvalidSignatureError
    from app.core.security import decode_access_token

    # Token signed with arbitrary different key
    tampered_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": 1000000000, "exp": 2000000000, "jti": str(uuid.uuid4())},
        "wrong_secret_key_at_least_32_characters_long!",
        algorithm="HS256",
    )

    with pytest.raises(InvalidSignatureError):
        decode_access_token(tampered_token)


def test_token_with_unsupported_algorithm_fails():
    """Verify that tokens with mismatched algorithms (e.g. none) are strictly rejected."""
    import uuid
    import jwt
    from jwt.exceptions import InvalidAlgorithmError, InvalidTokenError
    from app.core.security import decode_access_token

    # None algorithm token attempt
    none_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": 1000000000, "exp": 2000000000, "jti": str(uuid.uuid4())},
        key="",
        algorithm="none",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(none_token)


def test_decode_empty_or_malformed_token_fails():
    """Verify that empty, blank, or malformed strings raise appropriate errors."""
    from jwt.exceptions import DecodeError
    from app.core.security import decode_access_token

    with pytest.raises(ValueError, match="cannot be empty"):
        decode_access_token("")

    with pytest.raises(ValueError, match="cannot be empty"):
        decode_access_token("   ")

    with pytest.raises(DecodeError):
        decode_access_token("not.a.valid.jwt.token")


def test_token_subject_uuid_object_and_string_accepted():
    """Verify that both uuid.UUID and valid UUID strings are accepted as subject."""
    import uuid
    from app.core.security import create_access_token, decode_access_token

    raw_uuid = uuid.uuid4()
    # Test UUID object
    token_obj = create_access_token(subject=raw_uuid)
    claims_obj = decode_access_token(token_obj)
    assert claims_obj["sub"] == str(raw_uuid)

    # Test valid UUID string
    uuid_str = str(uuid.uuid4())
    token_str = create_access_token(subject=uuid_str)
    claims_str = decode_access_token(token_str)
    assert claims_str["sub"] == uuid_str


def test_token_creation_rejects_invalid_empty_or_malformed_subjects():
    """Verify that None, empty, malformed, or non-UUID subjects raise ValueError during token creation."""
    import pytest
    from app.core.security import create_access_token

    with pytest.raises(ValueError, match="Token subject cannot be None"):
        create_access_token(subject=None)

    with pytest.raises(ValueError, match="Token subject"):
        create_access_token(subject="")

    with pytest.raises(ValueError, match="Token subject"):
        create_access_token(subject="    ")

    with pytest.raises(ValueError, match="must be a valid UUID"):
        create_access_token(subject="not-a-valid-uuid")

    with pytest.raises(ValueError, match="must be a valid UUID"):
        create_access_token(subject=12345)


def test_decode_rejects_token_with_non_uuid_subject():
    """Verify that a correctly signed token containing a non-UUID subject claim is rejected."""
    import jwt
    import uuid
    from datetime import datetime, timezone, timedelta
    from jwt.exceptions import InvalidTokenError
    from app.core.security import decode_access_token, get_jwt_secret_key, validate_jwt_algorithm

    now = datetime.now(timezone.utc)
    # Token with non-UUID subject string
    payload = {
        "sub": "non-uuid-user-identity",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, get_jwt_secret_key(), algorithm=validate_jwt_algorithm())

    with pytest.raises(InvalidTokenError, match="must be a valid UUID string"):
        decode_access_token(token)


def test_decode_rejects_token_missing_jti():
    """Verify that a correctly signed token missing the mandatory jti claim is rejected."""
    import jwt
    import uuid
    from datetime import datetime, timezone, timedelta
    from jwt.exceptions import InvalidTokenError
    from app.core.security import decode_access_token, get_jwt_secret_key, validate_jwt_algorithm

    now = datetime.now(timezone.utc)
    # Token omitting jti claim
    payload = {
        "sub": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    token = jwt.encode(payload, get_jwt_secret_key(), algorithm=validate_jwt_algorithm())

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_token_with_empty_or_invalid_jti():
    """Verify that tokens with empty, whitespace, non-string, or non-UUID jti claims are rejected."""
    import jwt
    import uuid
    from datetime import datetime, timezone, timedelta
    from jwt.exceptions import InvalidTokenError
    from app.core.security import decode_access_token, get_jwt_secret_key, validate_jwt_algorithm

    now = datetime.now(timezone.utc)
    secret_key = get_jwt_secret_key()
    algo = validate_jwt_algorithm()

    for invalid_jti in ["", "   ", 12345, "not-a-valid-uuid-identifier"]:
        payload = {
            "sub": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": invalid_jti,
        }
        token = jwt.encode(payload, secret_key, algorithm=algo)
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)



