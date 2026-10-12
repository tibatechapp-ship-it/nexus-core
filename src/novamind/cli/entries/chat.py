"""
Chat API — Communicates with NovaMind via bridge.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

from app.core.security import get_current_user
from app.core.nova_bridge import nova_bridge
from app.models.user import User


router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    history: Optional[List[dict]] = None


class ChatResponse(BaseModel):
    ok: bool
    response: Optional[str] = None
    provider: Optional[str] = None
    error: Optional[str] = None


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
):
    """Send message to NovaMind."""
    # Check quota
    if user.ai_requests_today >= user.ai_requests_limit:
        raise HTTPException(
            429,
            f"تجاوزت الحد اليومي ({user.ai_requests_limit} طلب). جرب غداً."
        )

    result = await nova_bridge.chat(req.message, req.history)
    return ChatResponse(**result)


@router.get("/status")
async def status(user: User = Depends(get_current_user)):
    """NovaMind status."""
    return await nova_bridge.get_status()
