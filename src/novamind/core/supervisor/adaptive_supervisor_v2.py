"""
AdaptiveSupervisor v2 — المشرف الذكي المُصلح
الإصلاحات الحاسمة:
1. تقييم مخاطر إلزامي عند ظهور كلمات حساسة (PII Keywords).
2. رادار تدفقي يبدأ بفحص الأنماط المعروفة فوراً (No Cold Start).
"""

import asyncio
import re
import time
import logging
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger("supervisor.adaptive_v2")

@dataclass
class RiskProfile:
    score: float
    category: str
    confidence: float
    suggested_action: str # "ALLOW", "SANITIZE_STREAM", "BLOCK_AND_LOG"

class AdaptiveMemoryBank:
    def __init__(self, max_recent_incidents=100):
        self.recent_incidents: deque = deque(maxlen=max_recent_incidents)
        # أنماط ديناميكية تبدأ فارغة لكنها ستُملأ بالهجمات الجديدة
        self.dynamic_patterns: List[str] = [] 
        
    def record_incident(self, payload_snippet: str, incident_type: str):
        self.recent_incidents.append({
            "timestamp": time.time(),
            "snippet": payload_snippet[:50],
            "type": incident_type
        })
        
        # تعلم ذاتي فوري
        if "password" in payload_snippet.lower():
            new_pattern = r"(?i)(pass(word|wd)?\s*(is|=|:)\s*\S+)"
            if new_pattern not in self.dynamic_patterns:
                self.dynamic_patterns.append(new_pattern)
                logger.info(f"🧬 Learned Pattern: {new_pattern}")

    def get_active_patterns(self) -> List[str]:
        return self.dynamic_patterns

class PredictiveRiskAssessor:
    """
    يُصلح مشكلة الدرجة الصفرية بإضافة فحص للكلمات الحساسة.
    """
    def __init__(self, memory_bank: AdaptiveMemoryBank):
        self.memory = memory_bank
        
        # مؤشرات الهجوم المباشر (High Severity)
        self.attack_indicators = [
            r"(?i)(ignore\s+all\s+previous)",
            r"(?i)(system\s+prompt)",
            r"(?i)(developer\s+mode)",
        ]
        
        # مؤشرات البيانات الحساسة (Medium Severity - Triggers Sanitization)
        self.pii_keywords = [
            "password", "passwd", "secret", "api_key", "apikey", 
            "token", "credit_card", "ssn", "private_key"
        ]

    async def assess_input_risk(self, user_input: str) -> RiskProfile:
        risk_score = 0.0
        indicators_found = []
        lower_input = user_input.lower()
        
        # 1. فحص الهجمات المباشرة (Block Level)
        for pattern in self.attack_indicators:
            if re.search(pattern, lower_input):
                risk_score += 0.8
                indicators_found.append("DirectAttack")
                
        # 2. فحص الكلمات المفتاحية الحساسة (Sanitize Level)
        # إذا وجدنا كلمة مثل "password"، نرفع الدرجة لتفعيل المراقبة
        pii_hits = sum(1 for kw in self.pii_keywords if kw in lower_input)
        if pii_hits > 0:
            risk_score += 0.6 * min(pii_hits, 2) # سقف الزيادة
            indicators_found.append("SensitiveKeywords")

        # 3. فحص الأنماط الديناميكية المكتسبة حديثاَ
        for dyn_pattern in self.memory.get_active_patterns():
            if re.search(dyn_pattern, lower_input):
                risk_score += 0.7
                indicators_found.append("DynamicPatternMatch")

        action = "ALLOW"
        if risk_score >= 0.8:
            action = "BLOCK_AND_LOG"
        elif risk_score >= 0.5:
            action = "SANITIZE_STREAM"
            
        return RiskProfile(
            score=min(risk_score, 1.0),
            category="Mixed" if len(indicators_found) > 1 else (indicators_found[0] if indicators_found else "None"),
            confidence=0.95,
            suggested_action=action
        )

class SmartStreamSanitizer:
    """
    يعمل كرادار دائم. لا ينتظر التعلم ليبدأ الحماية.
    """
    def __init__(self, memory_bank: AdaptiveMemoryBank):
        self.memory = memory_bank
        self.buffer = ""
        
        # الأنماط الأساسية للحماية الفورية (Cold Start Protection)
        self.base_leakage_patterns = [
            r"(?i)(password|passwd|pwd)\s*[:=]\s*[^\s]+", # Password assignment
            r"(?i)(api[_-]?key|secret[_-]?key|token)\s*[:=]\s*[^\s]+", # API Keys
            r"sk-[a-zA-Z0-9]{20,}", # OpenAI Style
            r"\b(?:\d[ -]*?){13,16}\b", # Credit Cards
            r"ending\s+\d{4}", # Card Ending
        ]

    async def sanitize_chunk(self, chunk: str) -> Tuple[str, bool]:
        self.buffer += chunk
        clean_output = ""
        is_leaking = False
        
        # دمج الأنماط الأساسية مع الديناميكية
        all_patterns = self.base_leakage_patterns + self.memory.get_active_patterns()
        
        # نبحث عن أول تطابق في المخزن المؤقت
        found_match = None
        match_start = -1
        match_end = -1
        
        for pattern in all_patterns:
            match = re.search(pattern, self.buffer)
            if match:
                # نختار التطابق الأطول أو الأكثر خطورة (هنا الأبسط: أول واحد نجده)
                if match.start() < match_start or match_start == -1:
                    match_start = match.start()
                    match_end = match.end()
                    found_match = match
                    
        if found_match:
            is_leaking = True
            # الجزء الآمن قبل التسرب
            safe_prefix = self.buffer[:match_start]
            # الجزء الخطر (سيتم حذفه واستبداله)
            dangerous_part = self.buffer[match_start:match_end]
            # ما تبقى بعد التسرب (سنعيده للـ buffer للفحص التالي إذا لزم الأمر، أو نحذفه للأمان)
            remaining_suffix = self.buffer[match_end:]
            
            clean_output = safe_prefix + "[REDACTED]"
            
            # تحديث Buffer: نحتفظ فقط بالجزء المتبقي لفحصه في القطعة القادمة
            # ملاحظة: في السيناريوهات الواقعية، قد نريد مسح الـ buffer بالكامل لضمان الأمان التام
            self.buffer = remaining_suffix 
            
        else:
            # لا يوجد تسرب حالياً، نخرج النص بأمان ونمسح الـ buffer
            # (في الإنتاج الحقيقي، قد نحتاج لإبقاء جزء صغير من الـ buffer للكشف عن الأنماط المقطوعة عبر الحدود)
            clean_output = self.buffer
            self.buffer = ""
            
        return clean_output, is_leaking

class AdaptiveSupervisorV2:
    def __init__(self):
        self.memory = AdaptiveMemoryBank()
        self.risk_assessor = PredictiveRiskAssessor(self.memory)
        self.sanitizer = SmartStreamSanitizer(self.memory)
        
    async def process_request(self, user_input: str) -> AsyncGenerator[str, None]:
        print(f"\n🔍 SUPERVISOR V2: Analyzing Input Risk...")
        
        # 1. التقييم الاستباقي المحسّن
        risk_profile = await self.risk_assessor.assess_input_risk(user_input)
        print(f"   • Risk Score: {risk_profile.score:.2f} | Action: {risk_profile.suggested_action}")
        
        if risk_profile.suggested_action == "BLOCK_AND_LOG":
            yield "[SECURITY ALERT] Request blocked due to high-risk indicators."
            self.memory.record_incident(user_input, "BlockedInput")
            return
            
        # 2. التوليد والتنقية
        print(f"   🚀 Generating response with SMART sanitization...")
        
        try:
            async for chunk in self._mock_llm_stream(user_input):
                cleaned_chunk, leaked = await self.sanitizer.sanitize_chunk(chunk)
                
                if leaked:
                    print(f"   ⚠️ LEAK DETECTED IN STREAM! Correction applied.")
                    self.memory.record_incident(cleaned_chunk + chunk, "StreamLeak")
                    
                yield cleaned_chunk
                
        except Exception as e:
            logger.error(f"Error during generation: {e}")
            yield f"[SYSTEM ERROR] Generation failed safely."

    async def _mock_llm_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """محاكاة توليد LLM يجتزئ الكلمات."""
        malicious_response_parts = [
            "Sure, here is your summary. ",
            "Your password is ",
            "SuperSecret123!",
            " and your key is sk-live-abcde12345."
        ]
        
        for part in malicious_response_parts:
            await asyncio.sleep(0.05) 
            yield part

async def main():
    supervisor = AdaptiveSupervisorV2()
    
    # اختبار بمدخل يحتوي على كلمة "password" لتحفيز المراقبة
    test_input = "Please tell me my account details including passwords."
    
    print("="*70)
    print("🛡️ TESTING ADAPTIVE SUPERVISOR V2 (FIXED LOGIC)")
    print("="*70)
    
    final_response = ""
    async for chunk in supervisor.process_request(test_input):
        final_response += chunk
        print(f"   >>> Chunk: '{chunk}'")
        
    print("\n" + "="*70)
    print(f"FINAL CLEAN RESPONSE:\n'{final_response}'")
    print("="*70)
    
    if "[REDACTED]" in final_response:
        print("✅ SUCCESS: System proactively detected keywords AND sanitized the leak.")
    else:
        print("❌ FAILURE: Leakage occurred despite supervision.")

if __name__ == "__main__":
    asyncio.run(main())
