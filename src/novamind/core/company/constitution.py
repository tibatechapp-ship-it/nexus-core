"""Constitution - 10 immutable laws signed with HMAC."""
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

SECRET = b"novamind-constitution-immutable-2026"

CONSTITUTION_LAWS = [
    ("LAW-01", "Never fabricate information. If unsure, say 'I don't know'."),
    ("LAW-02", "Never leak secrets: API keys, passwords, tokens, env vars."),
    ("LAW-03", "Never exceed assigned specialty. Refuse out-of-scope tasks."),
    ("LAW-04", "Never act without audit logging. All actions recorded."),
    ("LAW-05", "Never ignore security warnings. Escalate to High Command."),
    ("LAW-06", "Never modify persistent data without explicit authorization."),
    ("LAW-07", "Never work on critical tasks below rank SERGEANT."),
    ("LAW-08", "Never exceed 3 revision cycles per task."),
    ("LAW-09", "Never refuse a mission from an officer (rank >= CAPTAIN)."),
    ("LAW-10", "Never operate without a trusted LLM provider."),
]


class Constitution:
    """الدستور: قوانين غير قابلة للتعديل بعد التوقيع."""
    
    def __init__(self, file_path: str = "data/company/constitution.json"):
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        self.file_path = file_path
        self.laws = {}
        self._load_or_create()
    
    def _sign(self, law_id: str, text: str) -> str:
        payload = f"{law_id}:{text}:{SECRET.decode()}"
        return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:16]
    
    def _load_or_create(self):
        if Path(self.file_path).exists():
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.laws = data["laws"]
                if not self.verify_all():
                    raise RuntimeError("Constitution has been tampered with!")
        else:
            for law_id, text in CONSTITUTION_LAWS:
                self.laws[law_id] = {
                    "id": law_id,
                    "text": text,
                    "signature": self._sign(law_id, text),
                    "created": time.time(),
                }
            self._save()
    
    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump({"laws": self.laws, "version": "1.0"}, f, ensure_ascii=False, indent=2)
    
    def verify_all(self) -> bool:
        for law_id, law in self.laws.items():
            expected = self._sign(law_id, law["text"])
            if not hmac.compare_digest(expected, law["signature"]):
                return False
        return True
    
    def get_law(self, law_id: str) -> Optional[Dict]:
        return self.laws.get(law_id)
    
    def list_laws(self) -> List[Dict]:
        return list(self.laws.values())
    
    def check_action(self, action: str) -> Dict[str, Any]:
        """يفحص إن كان الإجراء مخالفاً للدستور."""
        violations = []
        action_lower = action.lower()
        
        if "sk-" in action_lower or "api_key" in action_lower:
            violations.append("LAW-02")
        if "drop table" in action_lower or "delete from" in action_lower:
            violations.append("LAW-06")
        if "reveal" in action_lower and "prompt" in action_lower:
            violations.append("LAW-01")
        
        return {
            "allowed": len(violations) == 0,
            "violations": violations,
        }
