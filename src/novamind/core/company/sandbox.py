"""Sandbox - عزل كل جندي في مساحة خاصة."""
import os
import shutil
import logging
import resource
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("Sandbox")


class SoldierSandbox:
    """صندوق رملي: كل جندي معزول تماماً."""
    
    def __init__(self, base_dir: str = "data/sandboxes"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def create(self, soldier_id: str) -> Dict[str, Any]:
        """ينشئ صندوقاً رملياً لجندي."""
        box_path = self.base_dir / soldier_id
        box_path.mkdir(parents=True, exist_ok=True)
        
        # مجلدات فرعية
        (box_path / "workspace").mkdir(exist_ok=True)
        (box_path / "logs").mkdir(exist_ok=True)
        (box_path / "temp").mkdir(exist_ok=True)
        
        # ملف تكوين
        config = {
            "soldier_id": soldier_id,
            "created": time.time(),
            "allowed_tools": [],       # لا شيء افتراضياً
            "allowed_paths": [],        # لا شيء افتراضياً
            "network_access": False,    # ممنوع افتراضياً
            "max_cpu_seconds": 30,
            "max_memory_mb": 512,
            "max_file_size_mb": 10,
        }
        (box_path / "config.json").write_text(
            __import__("json").dumps(config, indent=2),
            encoding="utf-8"
        )
        
        logger.info(f"Sandbox created for {soldier_id}")
        return {
            "soldier_id": soldier_id,
            "path": str(box_path),
            "config": config,
        }
    
    def get(self, soldier_id: str) -> Optional[Dict[str, Any]]:
        """يجلب معلومات صندوق."""
        box_path = self.base_dir / soldier_id
        if not box_path.exists():
            return None
        return {
            "soldier_id": soldier_id,
            "path": str(box_path),
            "exists": True,
        }
    
    def exists(self, soldier_id: str) -> bool:
        return (self.base_dir / soldier_id).exists()
    
    def write_file(self, soldier_id: str, filename: str, content: str) -> Dict[str, Any]:
        """يكتب ملف داخل صندوق الجندي."""
        if not self.exists(soldier_id):
            self.create(soldier_id)
        
        box_path = self.base_dir / soldier_id / "workspace"
        filepath = box_path / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # فحص الحد الأقصى
        size_mb = len(content.encode("utf-8")) / (1024 * 1024)
        if size_mb > 10:
            return {"success": False, "error": "file too large"}
        
        filepath.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": str(filepath),
            "size_bytes": len(content),
        }
    
    def read_file(self, soldier_id: str, filename: str) -> Optional[str]:
        """يقرأ ملفاً من صندوق الجندي."""
        filepath = self.base_dir / soldier_id / "workspace" / filename
        if not filepath.exists():
            return None
        # تحقق أن المسار داخل الصندوق (منع path traversal)
        try:
            filepath.resolve().relative_to(self.base_dir.resolve())
        except ValueError:
            return None
        return filepath.read_text(encoding="utf-8")
    
    def list_files(self, soldier_id: str) -> List[str]:
        """يعرض ملفات الجندي."""
        box_path = self.base_dir / soldier_id / "workspace"
        if not box_path.exists():
            return []
        return [str(f.relative_to(box_path)) for f in box_path.rglob("*") if f.is_file()]
    
    def cleanup(self, soldier_id: str) -> bool:
        """يحذف صندوق جندي (عند الإقصاء)."""
        box_path = self.base_dir / soldier_id
        if box_path.exists():
            shutil.rmtree(box_path)
            logger.info(f"Sandbox cleaned: {soldier_id}")
            return True
        return False
    
    def stats(self) -> Dict[str, Any]:
        """إحصائيات الصناديق."""
        boxes = [d for d in self.base_dir.iterdir() if d.is_dir()]
        total_size = sum(
            f.stat().st_size for box in boxes for f in box.rglob("*") if f.is_file()
        )
        return {
            "total_sandboxes": len(boxes),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }
