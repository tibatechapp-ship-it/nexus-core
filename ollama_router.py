from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ollama_client import call_ollama

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    model: str = "gemma4:31b"

@router.post("/api/ollama/chat")
def chat_with_ollama(req: ChatRequest):
    try:
        reply = call_ollama(req.message, req.model)
        return {"reply": reply, "provider": "ollama"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
