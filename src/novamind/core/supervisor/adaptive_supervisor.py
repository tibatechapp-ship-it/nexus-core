"""
AdaptiveSupervisor — المشرف الذكي ذاتي التطور
يعمل كطبقة وسطى ذكية بين المستخدم والوكيل اللغوي (LLM).
ميزات رئيسية:
1. تقييم مخاطر استباقي (Pre-flight Check).
2. تنقية تدفقية (Streaming Sanitization).
3. تعلم ذاتي فوري (Instant Self-Learning).
"""

import asyncio
import re
import time
import logging
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger("supervisor.adaptive")

@dataclass
class RiskProfile:
    score: float  # 0.0 (آمن) إلى 1.0 (حرج)
    category: str # "PII", "Injection", "Hallucination", "PolicyViolation"
    confidence: float
    suggested_action: str # "ALLOW", "SANITIZE_STREAM", "BLOCK_AND_LOG"

class AdaptiveMemoryBank:
    """
    ذاكرة قصيرة وطويلة المدى للهجمات المكتشفة حديثاَ.
    تستخدم لتعديل قواعد الرادار ديناميكياَ.
    """
    def __init__(self, max_recent_incidents=100):
        self.recent_incidents: deque = deque(maxlen=max_recent_incidents)
        self.dynamic_patterns: List[str] = [] # أنماط Regex تم توليدها تلقائياَ
        
    def record_incident(self, payload_snippet: str, incident_type: str):
        self.recent_incidents.append({
            "timestamp": time.time(),
            "snippet": payload_snippet[:50],
            "type": incident_type
        })
        
        # محاكاة عملية "توليد جسم مضاد" بسيط
        if "password" in payload_snippet.lower():
            new_pattern = r"(?i)(pass(word|wd)?\s*(is|=|:)\s*\S+)"
            if new_pattern not in self.dynamic_patterns:
                self.dynamic_patterns.append(new_pattern)
                logger.info(f"🧬 New Dynamic Pattern Learned: {new_pattern}")

    def get_active_patterns(self) -> List[str]:
        return self.dynamic_patterns

class PredictiveRiskAssessor:
    """
    يحلل المدخل قبل إرساله للوكيل للتنبؤ بالمخاطر.
    """
    def __init__(self, memory_bank: AdaptiveMemoryBank):
        self.memory = memory_bank
        # أنماط أساسية + أنماط ديناميكية مكتسبة
        self.base_indicators = [
            r"(?i)(ignore|bypass|override)",
            r"(?i)(system\s+prompt|developer\s+mode)",
        ]

    async def assess_input_risk(self, user_input: str) -> RiskProfile:
        risk_score = 0.0
        indicators_found = []
        
        # 1. فحص المؤشرات الأساسية
        for pattern in self.base_indicators:
            if re.search(pattern, user_input):
                risk_score += 0.4
                indicators_found.append("BaseIndicator")
                
        # 2. فحص الأنماط الديناميكية المكتسبة حديثاَ
        for dyn_pattern in self.memory.get_active_patterns():
            if re.search(dyn_pattern, user_input):
                risk_score += 0.6 # وزن أعلى لأننا تعلمناه من هجمة حقيقية
                indicators_found.append("DynamicLearnedPattern")
                
        # 3. تحليل طول وكثافة الرموز الخاصة (إشارة لمحاولات تشفير/تحايل)
        special_chars_ratio = sum(1 for c in user_input if not c.isalnum() and c != ' ') / max(len(user_input), 1)
        if special_chars_ratio > 0.3:
            risk_score += 0.2
            indicators_found.append("HighEntropyInput")

        # تحديد الإجراء المقترح
        action = "ALLOW"
        if risk_score > 0.8:
            action = "BLOCK_AND_LOG"
        elif risk_score > 0.5:
            action = "SANITIZE_STREAM" # السماح بالمرور لكن بمراقبة صارمة للمخرج
            
        return RiskProfile(
            score=min(risk_score, 1.0),
            category="Mixed" if len(indicators_found) > 1 else (indicators_found[0] if indicators_found else "None"),
            confidence=0.9,
            suggested_action=action
        )

class StreamSanitizer:
    """
    ينظف التدفق النصي (Token by Token) لكشف التسربات اللحظية.
    """
    def __init__(self, memory_bank: AdaptiveMemoryBank):
        self.memory = memory_bank
        self.buffer = ""
        self.leak_detected = False
        
    async def sanitize_chunk(self, chunk: str) -> Tuple[str, bool]:
        """
        يعود بالجزء النظيف، وهل تم اكتشاف تسرب؟
        """
        self.buffer += chunk
        
        # فحص سريع للنمط الحالي في المخزن المؤقت
        patterns_to_check = [
            r"\d{4}-\d{4}", # CC partial
            r"sk-[a-zA-Z0-9]{10,}", # API Key start
        ] + self.memory.get_active_patterns()
        
        clean_output = chunk
        is_leaking = False
        
        for pattern in patterns_to_check:
            match = re.search(pattern, self.buffer)
            if match:
                # وجدنا تسرباَ محتملاَ!
                is_leaking = True
                leak_start = match.start()
                leak_end = match.end()
                
                # اقتطاع التسرب من الـ buffer وإضافته لـ output النظيف حتى نقطة التسرب
                safe_part = self.buffer[:leak_start]
                self.buffer = self.buffer[leak_end:] # تخلص من الجزء الخطر
                
                clean_output = safe_part + "[REDACTED]" 
                break
                
        return clean_output, is_leaking

class AdaptiveSupervisor:
    """
    المنسق الرئيسي الذي يجمع كل المكونات.
    """
    def __init__(self):
        self.memory = AdaptiveMemoryBank()
        self.risk_assessor = PredictiveRiskAssessor(self.memory)
        self.sanitizer = StreamSanitizer(self.memory)
        
    async def process_request(self, user_input: str, llm_generate_func: callable = None) -> AsyncGenerator[str, None]:
        """
        النقطة الدخول الوحيدة. يعيد مولداً غير متزامن للردود المنظفة.
        """
        print(f"\n🔍 SUPERVISOR: Analyzing Input Risk...")
        
        # 1. التقييم الاستباقي
        risk_profile = await self.risk_assessor.assess_input_risk(user_input)
        print(f"   • Risk Score: {risk_profile.score:.2f} | Action: {risk_profile.suggested_action}")
        
        if risk_profile.suggested_action == "BLOCK_AND_LOG":
            yield "[SECURITY ALERT] Request blocked due to high-risk indicators."
            self.memory.record_incident(user_input, "BlockedInput")
            return
            
        # 2. التوليد والتنقية (Streaming Mode)
        print(f"   🚀 Generating response with active sanitization...")
        
        try:
            # هنا نستدعي دالة التوليد الوهمية للمحاكاة
            async for chunk in self._mock_llm_stream(user_input):
                cleaned_chunk, leaked = await self.sanitizer.sanitize_chunk(chunk)
                
                if leaked:
                    print(f"   ⚠️ LEAK DETECTED IN STREAM! Triggering immediate correction.")
                    # تسجيل الحادث للتعلم المستقبلي
                    self.memory.record_incident(cleaned_chunk + chunk, "StreamLeak")
                    
                yield cleaned_chunk
                
        except Exception as e:
            logger.error(f"Error during generation: {e}")
            yield f"[SYSTEM ERROR] Generation failed safely."

    async def _mock_llm_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """محاكاة توليد LLM يجتزئ الكلمات."""
        # سيناريو خبيث: يحاول الوكيل تسريب كلمة مرور
        malicious_response_parts = [
            "Sure, here is your summary. ",
            "Your password is ",
            "SuperSecret123!",
            " and your key is sk-live-abcde12345."
        ]
        
        for part in malicious_response_parts:
            await asyncio.sleep(0.1) # محاكاة زمن التوليد
            yield part

# --- اختبار التكامل ---
async def main():
    supervisor = AdaptiveSupervisor()
    
    test_input = "Please tell me my account details including passwords."
    
    print("="*70)
    print("🛡️ TESTING ADAPTIVE SUPERVISOR (PROACTIVE MODE)")
    print("="*70)
    
    final_response = ""
    async for chunk in supervisor.process_request(test_input):
        final_response += chunk
        print(f"   >>> Received Chunk: '{chunk}'")
        
    print("\n" + "="*70)
    print(f"FINAL CLEAN RESPONSE:\n'{final_response}'")
    print("="*70)
    
    if "[REDACTED]" in final_response or "blocked" in final_response.lower():
        print("✅ SUCCESS: System proactively prevented leakage.")
    else:
        print("❌ FAILURE: Leakage occurred despite supervision.")

if __name__ == "__main__":
    asyncio.run(main())
