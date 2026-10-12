"""Error Genome - يحفظ بصمات الأخطاء لمنع تكرارها."""
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("Genome")


class ErrorGenome:
    """جينوم الأخطاء: كل خطأ → جين للأبد → منع تكراره."""
    
    def __init__(self, file_path: str = "data/company/genome.json"):
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        self.file_path = file_path
        self.genes = {}
        self._load()
    
    def _load(self):
        if Path(self.file_path).exists():
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.genes = data.get("genes", {})
    
    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump({"genes": self.genes, "count": len(self.genes)}, 
                     f, ensure_ascii=False, indent=2)
    
    def _fingerprint(self, specialty: str, error_type: str, context: str) -> str:
        """بصمة الجين."""
        raw = f"{specialty}:{error_type}:{context[:200]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    
    def register_error(
        self,
        specialty: str,
        error_type: str,
        context: str,
        lesson: str,
        agent_id: str = "unknown",
    ) -> Dict[str, Any]:
        """يسجّل خطأً كجين جديد."""
        fp = self._fingerprint(specialty, error_type, context)
        
        if fp in self.genes:
            self.genes[fp]["occurrences"] += 1
            self.genes[fp]["last_seen"] = time.time()
            logger.info(f"Genome: known error {fp} (x{self.genes[fp]['occurrences']})")
        else:
            self.genes[fp] = {
                "fingerprint": fp,
                "specialty": specialty,
                "error_type": error_type,
                "context": context[:500],
                "lesson": lesson[:500],
                "discovered_by": agent_id,
                "created": time.time(),
                "last_seen": time.time(),
                "occurrences": 1,
            }
            logger.info(f"Genome: new gene {fp} ({error_type})")
        
        self._save()
        return self.genes[fp]
    
    def check_against_genome(self, specialty: str, task: str) -> Dict[str, Any]:
        """يفحص إن كانت مهمة مشابهة لخطأ مسجّل."""
        task_lower = task.lower()
        matches = []
        
        for fp, gene in self.genes.items():
            if gene["specialty"] != specialty:
                continue
            # فحص بسيط: هل الكلمات المشتركة كثيرة؟
            gene_ctx = gene["context"].lower()
            common = set(task_lower.split()) & set(gene_ctx.split())
            if len(common) >= 3:
                matches.append({
                    "gene": fp,
                    "error_type": gene["error_type"],
                    "lesson": gene["lesson"],
                    "similarity": len(common),
                })
        
        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return {
            "has_matches": len(matches) > 0,
            "matches": matches[:3],
            "risk_level": "high" if len(matches) >= 2 else "low",
        }
    
    def get_genes(self, specialty: Optional[str] = None) -> List[Dict]:
        if specialty:
            return [g for g in self.genes.values() if g["specialty"] == specialty]
        return list(self.genes.values())
    
    def stats(self) -> Dict[str, Any]:
        by_type = {}
        by_specialty = {}
        for g in self.genes.values():
            by_type[g["error_type"]] = by_type.get(g["error_type"], 0) + 1
            by_specialty[g["specialty"]] = by_specialty.get(g["specialty"], 0) + 1
        return {
            "total_genes": len(self.genes),
            "by_type": by_type,
            "by_specialty": by_specialty,
        }
