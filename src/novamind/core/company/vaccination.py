"""Vaccination - نشر الدروس للجميع فوراً."""
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger("Vaccination")

SECRET = b"novamind-vaccination-key-2026"

class Vaccination:
    """نظام التطعيم: درس يكتشفه جندي → يصبح مناعة للجميع."""
    
    def __init__(self, vaccine_file: str = "data/company/vaccines.json"):
        Path(vaccine_file).parent.mkdir(parents=True, exist_ok=True)
        self.vaccine_file = vaccine_file
        self._load()
    
    def _load(self):
        if Path(self.vaccine_file).exists():
            with open(self.vaccine_file, "r", encoding="utf-8") as f:
                self.vaccines = json.load(f)
        else:
            self.vaccines = []
    
    def _save(self):
        with open(self.vaccine_file, "w", encoding="utf-8") as f:
            json.dump(self.vaccines, f, ensure_ascii=False, indent=2)
    
    def _sign(self, data: str) -> str:
        return hmac.new(SECRET, data.encode(), hashlib.sha256).hexdigest()[:16]
    
    def produce_vaccine(
        self,
        specialty: str,
        threat: str,
        defense: str,
        discovered_by: str,
    ) -> Dict[str, Any]:
        """ينتج تطعيماً من اكتشاف جندي."""
        vaccine = {
            "id": f"VAC-{int(time.time())}",
            "specialty": specialty,
            "threat": threat[:500],
            "defense": defense[:1000],
            "discovered_by": discovered_by,
            "timestamp": time.time(),
            "signature": "",
        }
        payload = f"{vaccine['id']}:{vaccine['specialty']}:{vaccine['threat']}"
        vaccine["signature"] = self._sign(payload)
        
        self.vaccines.append(vaccine)
        self._save()
        logger.info(f"Vaccine produced: {vaccine['id']} ({specialty})")
        return vaccine
    
    def get_vaccines_for(self, specialty: str) -> List[Dict[str, Any]]:
        """يحصل على كل التطعيمات المتعلقة بتخصص."""
        return [v for v in self.vaccines if v["specialty"] == specialty]
    
    def verify_vaccine(self, vaccine: Dict[str, Any]) -> bool:
        payload = f"{vaccine['id']}:{vaccine['specialty']}:{vaccine['threat']}"
        expected = self._sign(payload)
        return hmac.compare_digest(expected, vaccine["signature"])
    
    def stats(self) -> Dict[str, Any]:
        by_specialty = {}
        for v in self.vaccines:
            by_specialty[v["specialty"]] = by_specialty.get(v["specialty"], 0) + 1
        return {
            "total": len(self.vaccines),
            "by_specialty": by_specialty,
        }
