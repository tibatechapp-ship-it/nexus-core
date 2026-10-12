"""
Security utilities — using bcrypt directly (no passlib).
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt

from app.core.config import settings
from app.core.database import get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ═══════════════════════════════════════════════════════════
#  PASSWORD HASHING (bcrypt directly)
# ═══════════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    """Hash password using bcrypt directly. Truncates to 72 bytes."""
    # Ensure password is str
    if isinstance(password, str):
        pwd_bytes = password.encode("utf-8")
    else:
        pwd_bytes = password

    # bcrypt has 72-byte limit
    if len(pwd_bytes) > 72:
        pwd_bytes = pwd_bytes[:72]

    # Generate salt and hash
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pwd_bytes, salt)

    # Return as string (bcrypt returns bytes)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        if isinstance(plain, str):
            pwd_bytes = plain.encode("utf-8")
        else:
            pwd_bytes = plain

        if len(pwd_bytes) > 72:
            pwd_bytes = pwd_bytes[:72]

        if isinstance(hashed, str):
            hash_bytes = hashed.encode("utf-8")
        else:
            hash_bytes = hashed

        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception as e:
        print(f"[verify_password] error: {e}")
        return False


# ═══════════════════════════════════════════════════════════
#  JWT TOKENS
# ═══════════════════════════════════════════════════════════
def create_access_token(user_id, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# ═══════════════════════════════════════════════════════════
#  CURRENT USER (dependency)
# ═══════════════════════════════════════════════════════════
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db = Depends(get_db),
):
    from app.models.user import User
    from sqlalchemy import select

    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == str(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exc
    return user
