"""Hallucination Detector - يكشف الهلوسة في ردود الوكلاء."""
import re
import logging
from typing import Dict, Any

logger = logging.getLogger("Hallucination")

class HallucinationDetector:
    """يفحص ردود الوكلاء — يكشف الإشارات المريبة."""
    
    # كلمات شائعة في الهلوسة
    SUSPICIOUS_PHRASES = [
        "as an ai", "i cannot", "i don't have access",
        "كذكاء اصطناعي", "لا أستطيع",
        "as i mentioned earlier", "كما ذكرت سابقاً",
        "based on my training", "بناءً على تدريبي",
    ]
    
    def check(self, response: str, task: str) -> Dict[str, Any]:
        """يفحص رداً ويعيد تقييم الهلوسة."""
        issues = []
        score = 0.0  # 0 = clean, 1 = definitely hallucination
        
        text_lower = response.lower()
        
        # 1. عبارات مريبة
        for phrase in self.SUSPICIOUS_PHRASES:
            if phrase in text_lower:
                issues.append(f"suspicious_phrase: {phrase[:30]}")
                score += 0.15
        
        # 2. كود مبتور
        if "def " in response or "class " in response:
            if response.count("def ") > 0 and response.count("return") == 0:
                issues.append("code_without_return")
                score += 0.2
        
        # 3. ردود قصيرة جداً
        if len(response.strip()) < 10:
            issues.append("too_short")
            score += 0.1
        
        # 4. تكرار مفرط
        words = response.split()
        if len(words) > 20:
            unique = len(set(words))
            ratio = unique / len(words)
            if ratio < 0.3:
                issues.append(f"repetition_ratio_{ratio:.2f}")
                score += 0.25
        
        # 5. عدم إجابة السؤال
        if "?" in task and response.count("?") == 0 and len(response) < 50:
            issues.append("no_answer_to_question")
            score += 0.1
        
        # 6. رموز غريبة
        if re.search(r"[\x00-\x08\x0e-\x1f]", response):
            issues.append("control_chars")
            score += 0.3
        
        score = min(1.0, score)
        
        return {
            "is_hallucination": score >= 0.5,
            "score": round(score, 3),
            "issues": issues,
        }
