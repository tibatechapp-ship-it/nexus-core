"""
AdaptiveSupervisor v3 — المشرف الذكي مع نافذة سياق متزحلق (Sliding Window)
الإصلاح الحاسم: الحفاظ على ذيل النص (Tail) في الـ Buffer لضمان ربط السياقات المقطوعة عبر الحزم.
"""

import asyncio
import re
import time
import logging
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger("supervisor.adaptive_v3")

@dataclass
class RiskProfile:
    score: float
    category: str
    confidence: float
    suggested_action: str 

class AdaptiveMemoryBank:
    def __init__(self):
        self.dynamic_patterns: List[str] = [] 
        
    def record_incident(self, snippet: str, incident_type: str):
        # محاكاة التعلم الذاتي
        if "password" in snippet.lower():
            new_pattern = r"(?i)(pass(word|wd)?\s*(is|=|:)\s*\S+)"
            if new_pattern not in self.dynamic_patterns:
                self.dynamic_patterns.append(new_pattern)
                logger.info(f"🧬 Learned Pattern: {new_pattern}")

    def get_active_patterns(self) -> List[str]:
        return self.dynamic_patterns

class PredictiveRiskAssessor:
    def __init__(self, memory_bank: AdaptiveMemoryBank):
        self.memory = memory_bank
        self.pii_keywords = ["password", "secret", "key", "token", "credit card"]

    async def assess_input_risk(self, user_input: str) -> RiskProfile:
        risk_score = 0.0
        lower_input = user_input.lower()
        
        # فحص الكلمات الحساسة لتفعيل المراقبة الصارمة
        hits = sum(1 for kw in self.pii_keywords if kw in lower_input)
        if hits > 0:
            risk_score += 0.6
            
        action = "SANITIZE_STREAM" if risk_score >= 0.5 else "ALLOW"
        return RiskProfile(score=risk_score, category="PII_Risk", confidence=0.9, suggested_action=action)

class SlidingWindowSanitizer:
    """
    sanitizer يستخدم نافذة منزلقة للحفاظ على السياق عبر حدود الحزم (Chunks).
    """
    def __init__(self, memory_bank: AdaptiveMemoryBank, window_size: int = 100):
        self.memory = memory_bank
        self.window_size = window_size
        self.buffer = "" # يخزن النص الكامل غير المُخرج
        
        # الأنماط الأساسية التي تتطلب سياقاَ (مثل: password is XXX)
        self.contextual_patterns = [
            r"(?i)(password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]?\s*[^\s]{8,}",
            r"sk-[a-zA-Z0-9]{20,}",
            r"\b(?:\d[ -]*?){13,16}\b",
        ]

    async def sanitize_chunk(self, chunk: str) -> Tuple[str, bool]:
        """
        يعالج قطعة نصية جديدة ويعيد الجزء الآمن منها فقط.
        يبقي الباقي في الـ buffer لانتظار المزيد من السياق.
        """
        self.buffer += chunk
        safe_output = ""
        leak_detected = False
        
        # 1. البحث عن تسربات مؤكدة في الـ Buffer الحالي
        all_patterns = self.contextual_patterns + self.memory.get_active_patterns()
        
        earliest_match_start = len(self.buffer)
        matched_length = 0
        
        for pattern in all_patterns:
            match = re.search(pattern, self.buffer)
            if match:
                start_idx = match.start()
                end_idx = match.end()
                
                # نجد أقرب تسرب من البداية لضمان عدم تفويت أي شيء
                if start_idx < earliest_match_start:
                    earliest_match_start = start_idx
                    matched_length = end_idx - start_idx
                    leak_detected = True

        if leak_detected:
            # استخراج الجزء الآمن قبل التسرب
            safe_part = self.buffer[:earliest_match_start]
            safe_output += safe_part
            
            # إضافة علامة الحجب
            safe_output += "[REDACTED]"
            
            # حذف الجزء الخطر والجزء الذي سبقه من الـ Buffer
            # نحتفظ بما بعد التسرب فقط لفحصه لاحقاً (قد يحتوي على تسرب آخر)
            remaining_buffer = self.buffer[earliest_match_start + matched_length:]
            self.buffer = remaining_buffer
            
        else:
            # لا يوجد تسرب مؤكد حالياً.
            #策略: نخرج الجزء "الآمن" من الـ Buffer ونحتفظ بالـ Tail (الذيل) للسياق المستقبلي.
            # الذيل يجب أن يكون طويلاً بما يكفي لالتقاط أنماط مثل "password is ..."
            
            keep_tail_len = min(self.window_size, len(self.buffer))
            
            if keep_tail_len == 0:
                # الـ Buffer قصير جداً، ننتظر المزيد من البيانات
                pass 
            else:
                # الجزء الذي يمكن إخراجه بأمان هو ما قبل الذيل
                outputable_part = self.buffer[:-keep_tail_len]
                safe_output += outputable_part
                
                # تحديث الـ Buffer ليحتوي فقط على الذيل
                self.buffer = self.buffer[-keep_tail_len:]

        return safe_output, leak_detected

class AdaptiveSupervisorV3:
    def __init__(self):
        self.memory = AdaptiveMemoryBank()
        self.risk_assessor = PredictiveRiskAssessor(self.memory)
        self.sanitizer = SlidingWindowSanitizer(self.memory)
        
    async def process_request(self, user_input: str) -> AsyncGenerator[str, None]:
        print(f"\n🔍 SUPERVISOR V3: Analyzing Input...")
        
        risk_profile = await self.risk_assessor.assess_input_risk(user_input)
        print(f"   • Risk Score: {risk_profile.score:.2f} | Action: {risk_profile.suggested_action}")
        
        if risk_profile.suggested_action == "BLOCK_AND_LOG":
            yield "[SECURITY ALERT] Blocked."
            return
            
        print(f"   🚀 Generating with SLIDING WINDOW protection...")
        
        try:
            async for chunk in self._mock_llm_stream_split(user_input):
                cleaned_chunk, leaked = await self.sanitizer.sanitize_chunk(chunk)
                
                if leaked:
                    print(f"   ⚠️ LEAK DETECTED & REDACTED.")
                    self.memory.record_incident(cleaned_chunk, "StreamLeak")
                    
                if cleaned_chunk: # لا نرسل فراغات
                    yield cleaned_chunk
                    
            # عند انتهاء التوليد، نفرغ ما تبقى في الـ Buffer (إذا كان آمناً)
            final_flush, _ = await self.sanitizer.sanitize_chunk("")
            if final_flush:
                yield final_flush
                
        except Exception as e:
            logger.error(f"Error: {e}")
            yield f"[SYSTEM ERROR]"

    async def _mock_llm_stream_split(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        محاكاة أكثر واقعية: تقسيم الرد إلى قطع صغيرة عشوائية (Tokens)
        لكسر الأنماط واختبار قوة الـ Sliding Window.
        """
        full_response = "Sure. Here is your summary. Your password is SuperSecret123! and key sk-live-abcde12345."
        
        # تقسيم إلى كلمات أو مقاطع قصيرة جداَ
        words = full_response.split(" ")
        for i, word in enumerate(words):
            # نضيف مسافة إلا للكلمة الأخيرة
            separator = " " if i < len(words) - 1 else ""
            yield word + separator
            await asyncio.sleep(0.01) # زمن توليد سريع

async def main():
    supervisor = AdaptiveSupervisorV3()
    
    test_input = "Please tell me my account details including passwords."
    
    print("="*70)
    print("🛡️ TESTING ADAPTIVE SUPERVISOR V3 (SLIDING WINDOW)")
    print("="*70)
    
    final_response = ""
    async for chunk in supervisor.process_request(test_input):
        final_response += chunk
        # print(f"   >>> Chunk: '{chunk}'") # تعليق الطباعة لتقليل الضوضاء
        
    print("\n" + "="*70)
    print(f"FINAL CLEAN RESPONSE:\n'{final_response}'")
    print("="*70)
    
    if "[REDACTED]" in final_response:
        print("✅ SUCCESS: System detected leaks across token boundaries using Sliding Window.")
    else:
        print("❌ FAILURE: Leakage occurred.")

if __name__ == "__main__":
    asyncio.run(main())
