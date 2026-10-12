"""Anti-Hallucination - يمنع الهلوسة في كل النماذج والوكلاء."""
import re
import logging
import json
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("AntiHall")


# ═══════════════════════════════════════════════════════
#  طبقات الكشف
# ═══════════════════════════════════════════════════════

class AntiHallucination:
    """حارس الهلوسة: 5 طبقات فحص."""
    
    # طبقة 1: أنماط الهلوسة الشائعة
    HALLUCINATION_PATTERNS = {
        "fake_citations": [
            r"according to (?:the )?(?:source|paper|study|article) (?:at|from) \d+",
            r"https?://(?:example|fake|test)\.com",
            r"\[\d+\]\(\s*\)",  # empty citation
        ],
        "fake_apis": [
            r"\.(?:execute_async_task|call_magic|auto_fix|self_heal)\(",
            r"import (?:numpy_ai|smart_lib|super_module)",
        ],
        "overconfidence": [
            r"i (?:am|'m) \d{3,}% sure",
            r"definitely, absolutely, always works",
            r"100% accurate guaranteed",
        ],
        "nonsense_phrases": [
            r"as an ai language model",
            r"as i mentioned (?:earlier|above|before) (?:in my|during our)",
            r"according to my training data from",
        ],
        "empty_or_trivial": [
            r"^(?:yes|no|ok|sure|fine)\.?\s*$",
            r"^i (?:don't know|am not sure)\.?\s*$",
        ],
        "repetition": [
            r"(.{10,}?)\1{3,}",  # نفس النص 3+ مرات
        ],
    }
    
    # طبقة 2: الكلمات المشبوهة في السياق التقني
    TECH_SUSPICIOUS = {
        "coder": [
            "def solve_magic",
            "async def auto_",
            "# TODO: implement",
            "raise NotImplementedError",
            "pass  # placeholder",
        ],
        "security": [
            "safe_but_actually",
            "trust_me_bro",
            "no_vulnerability_here",
        ],
    }
    
    # طبقة 3: التحقق من البنية
    STRUCTURE_CHECKS = {
        "coder": {
            "must_contain": ["def ", "return"],
            "must_not_contain": ["pass  #", "NotImplementedError", "TODO"],
        },
        "tester": {
            "must_contain": ["def test_", "assert"],
        },
        "security": {
            "must_contain_any": ["VULNERABILITY", "SEVERITY", "FIX", "SAFE"],
        },
    }
    
    def __init__(self, llm_router=None, strict_mode: bool = True):
        self.llm = llm_router
        self.strict = strict_mode
        self.checks_run = 0
        self.rejections = 0
        self.warnings = 0
        self.log: List[Dict] = []
    
    # ═══════════════════════════════════════════════════
    #  الطبقة 1: فحص الأنماط
    # ═══════════════════════════════════════════════════
    def _check_patterns(self, response: str) -> List[str]:
        """يفحص الأنماط المريبة."""
        issues = []
        text = response.lower()
        
        for category, patterns in self.HALLUCINATION_PATTERNS.items():
            for pattern in patterns:
                try:
                    if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                        issues.append(f"{category}:matched")
                        break
                except re.error:
                    pass
        
        return issues
    
    # ═══════════════════════════════════════════════════
    #  الطبقة 2: فحص المحتوى التقني
    # ═══════════════════════════════════════════════════
    def _check_tech_content(self, response: str, specialty: str) -> List[str]:
        """يفحص المحتوى التقني."""
        issues = []
        
        suspicious = self.TECH_SUSPICIOUS.get(specialty, [])
        for s in suspicious:
            if s.lower() in response.lower():
                issues.append(f"suspicious:{s[:30]}")
        
        return issues
    
    # ═══════════════════════════════════════════════════
    #  الطبقة 3: فحص البنية
    # ═══════════════════════════════════════════════════
    def _check_structure(self, response: str, specialty: str) -> List[str]:
        """يفحص بنية الرد."""
        issues = []
        checks = self.STRUCTURE_CHECKS.get(specialty, {})
        
        # must_contain
        for must in checks.get("must_contain", []):
            if must not in response:
                issues.append(f"missing:{must}")
        
        # must_contain_any
        any_list = checks.get("must_contain_any", [])
        if any_list and not any(k in response for k in any_list):
            issues.append(f"missing_any:{','.join(any_list[:3])}")
        
        # must_not_contain
        for forbidden in checks.get("must_not_contain", []):
            if forbidden in response:
                issues.append(f"contains:{forbidden}")
        
        return issues
    
    # ═══════════════════════════════════════════════════
    #  الطبقة 4: التحقق من النموذج (Self-Reflection)
    # ═══════════════════════════════════════════════════
    async def _check_with_llm(
        self,
        task: str,
        response: str,
        specialty: str,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """يطلب من النموذج التحقق من رده."""
        if not self.llm:
            return {"skipped": True}
        
        import asyncio
        prompt = f"""You are a HALLUCINATION DETECTOR.

Task given to agent:
{task[:500]}

Agent's response:
{response[:1500]}

Analyze if the response contains hallucinations.
Answer ONLY with JSON:
{{
  "is_hallucination": true|false,
  "confidence": 0.0-1.0,
  "reason": "short reason"
}}"""
        
        try:
            result = await asyncio.wait_for(
                self.llm.generate(prompt, system_prompt="You are a factual accuracy checker."),
                timeout=timeout,
            )
            
            # استخرج JSON
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return {
                    "is_hallucination": bool(data.get("is_hallucination", False)),
                    "confidence": float(data.get("confidence", 0.5)),
                    "reason": str(data.get("reason", ""))[:200],
                }
        except Exception as e:
            logger.debug(f"LLM check failed: {e}")
        
        return {"skipped": True, "error": True}
    
    # ═══════════════════════════════════════════════════
    #  الواجهة الرئيسية
    # ═══════════════════════════════════════════════════
    async def check(
        self,
        task: str,
        response: str,
        specialty: str,
        use_llm: bool = False,
    ) -> Dict[str, Any]:
        """يفحص رداً بكل الطبقات."""
        self.checks_run += 1
        
        issues = []
        warnings = []
        
        # 1. patterns
        pattern_issues = self._check_patterns(response)
        issues.extend(pattern_issues)
        
        # 2. tech content
        tech_issues = self._check_tech_content(response, specialty)
        warnings.extend(tech_issues)
        
        # 3. structure
        struct_issues = self._check_structure(response, specialty)
        warnings.extend(struct_issues)
        
        # 4. LLM (اختياري)
        llm_check = {"skipped": True}
        if use_llm and self.llm:
            llm_check = await self._check_with_llm(task, response, specialty)
            if llm_check.get("is_hallucination"):
                if llm_check.get("confidence", 0) >= 0.7:
                    issues.append(f"llm_hallucination:{llm_check.get('reason', '')[:50]}")
                else:
                    warnings.append(f"llm_uncertain:{llm_check.get('reason', '')[:50]}")
        
        # القرار
        if issues:
            if self.strict or len(issues) >= 2:
                decision = "REJECT"
                self.rejections += 1
            else:
                decision = "WARN"
                self.warnings += 1
        elif warnings:
            decision = "WARN"
            self.warnings += 1
        else:
            decision = "ALLOW"
        
        result = {
            "decision": decision,
            "issues": issues,
            "warnings": warnings,
            "llm_check": llm_check,
            "specialty": specialty,
            "checks_run": self.checks_run,
        }
        
        self.log.append(result)
        return result
    
    def stats(self) -> Dict[str, Any]:
        return {
            "checks": self.checks_run,
            "rejections": self.rejections,
            "warnings": self.warnings,
            "rejection_rate": round(self.rejections / max(self.checks_run, 1), 3),
        }


# ═══════════════════════════════════════════════════════
#  Global singleton
# ═══════════════════════════════════════════════════════
_anti_hall_global: Optional[AntiHallucination] = None


def get_anti_hallucination(llm_router=None) -> AntiHallucination:
    """يرجع النسخة العالمية."""
    global _anti_hall_global
    if _anti_hall_global is None:
        _anti_hall_global = AntiHallucination(llm_router=llm_router)
    return _anti_hall_global
