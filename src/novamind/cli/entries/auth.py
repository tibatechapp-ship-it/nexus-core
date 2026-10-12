"""
Auth API — Fixed with better error handling.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timezone
import uuid
import logging

from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password, create_access_token,
    get_current_user,
)
from app.models.user import User, UserRole

logger = logging.getLogger("auth")
router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: str
    role: str
    ai_requests_today: int
    ai_requests_limit: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/register", response_model=TokenResponse,
             status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        logger.info(f"Register attempt: {req.email}")

        # Check email
        exists = await db.execute(select(User).where(User.email == req.email))
        if exists.scalar_one_or_none():
            raise HTTPException(409, "البريد الإلكتروني مسجل مسبقاً")

        # Check username
        exists = await db.execute(select(User).where(User.username == req.username))
        if exists.scalar_one_or_none():
            raise HTTPException(409, "اسم المستخدم مأخوذ")

        # Create user
        user = User(
            id=str(uuid.uuid4()),
            email=req.email,
            username=req.username,
            full_name=req.full_name,
            hashed_password=hash_password(req.password),
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(f"User registered: {user.email}")

        token = create_access_token(user.id)
        return TokenResponse(access_token=token, expires_in=60 * 24 * 60)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Register error: {e}")
        await db.rollback()
        raise HTTPException(500, f"خطأ في التسجيل: {str(e)[:100]}")


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        logger.info(f"Login attempt: {req.email}")

        result = await db.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(401, "البريد أو كلمة المرور غير صحيحة")

        if not verify_password(req.password, user.hashed_password):
            raise HTTPException(401, "البريد أو كلمة المرور غير صحيحة")

        if not user.is_active:
            raise HTTPException(403, "الحساب معطل")

        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(f"User logged in: {user.email}")

        token = create_access_token(user.id)
        return TokenResponse(access_token=token, expires_in=60 * 24 * 60)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Login error: {e}")
        await db.rollback()
        raise HTTPException(500, f"خطأ في الدخول: {str(e)[:100]}")


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role.value,
        ai_requests_today=user.ai_requests_today,
        ai_requests_limit=user.ai_requests_limit,
        is_active=user.is_active,
        created_at=user.created_at,
    )
