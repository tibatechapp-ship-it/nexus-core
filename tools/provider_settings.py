from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os

router = APIRouter()

class ProviderKey(BaseModel):
    provider: str
    api_key: str

@router.post("/api/settings/provider")
def set_provider_key(data: ProviderKey):
    if not data.api_key or len(data.api_key) < 10:
        raise HTTPException(400, detail="مفتاح غير صالح")
    
    # قراءة .env الحالي
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    # اسم المتغير حسب المزود
    key_name = f"{data.provider.upper()}_API_KEY"
    
    # تحديث أو إضافة المتغير
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key_name}="):
            lines[i] = f"{key_name}={data.api_key}\n"
            found = True
            break
    
    if not found:
        lines.append(f"{key_name}={data.api_key}\n")
    
    # حفظ الملف
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    return {"status": "ok", "message": f"تم حفظ مفتاح {data.provider} بنجاح"}
