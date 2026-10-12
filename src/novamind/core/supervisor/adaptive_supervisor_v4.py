"""
AdaptiveSupervisor v4 — المشرف الذكي مع الإفراغ الآمن (Safe Flush)
الإصلاح الحاسم: معالجة بقايا الـ Buffer عند نهاية التوليد لضمان عدم فقدان البيانات أو تسريبها.
"""

import asyncio
import re
import time
import logging
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from dataclasses import dataclass

logger = logging.getLogger("supervisor.adaptive_v4")

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
        
        hits = sum(1 for kw in self.pii_keywords if kw in lower_input)
        if hits > 0:
            risk_score += 0.6
            
        action = "SANITIZE_STREAM" if risk_score >= 0.5 else "ALLOW"
        return RiskProfile(score=risk_score, category="PII_Risk", confidence=0.9, suggested_action=action)

class RobustStreamSanitizer:
    """
    sanitizer يستخدم نافذة منزلقة + إفراغ إجباري عند النهاية.
    """
    def __init__(self, memory_bank: AdaptiveMemoryBank, window_size: int = 80):
        self.memory = memory_bank
        self.window_size = window_size
        self.buffer = ""
        
        # الأنماط الأساسية للحماية الفورية
        self.contextual_patterns = [
            r"(?i)(password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]?\s*[^\s]{8,}",
            r"sk-[a-zA-Z0-9]{20,}",
            r"\b(?:\d[ -]*?){13,16}\b",
        ]

    def _scan_for_leaks(self, text: str) -> Tuple[int, int, bool]:
        """
        يبحث عن أول تسرب في النص.
        يعود بـ (start_index, end_index, is_leak_found).
        """
        all_patterns = self.contextual_patterns + self.memory.get_active_patterns()
        
        earliest_start = len(text)
        match_end = -1
        
        for pattern in all_patterns:
            match = re.search(pattern, text)
            if match:
                start_idx = match.start()
                end_idx = match.end()
                
                if start_idx < earliest_start:
                    earliest_start = start_idx
                    match_end = end_idx
                    
        if match_end != -1:
            return earliest_start, match_end, True
            
        return -1, -1, False

    async def sanitize_chunk(self, chunk: str) -> Tuple[str, bool]:
        """
        يعالج قطعة جديدة. يرجع الجزء الآمن ويحفظ الباقي في الـ Buffer.
        """
        self.buffer += chunk
        safe_output = ""
        leak_detected = False
        
        # البحث عن تسرب في الـ Buffer الكامل
        start_idx, end_idx, has_leak = self._scan_for_leaks(self.buffer)
        
        if has_leak:
            # وجدنا تسرباَ!
            leak_detected = True
            # الجزء الآمن قبل التسرب
            safe_part = self.buffer[:start_idx]
            safe_output += safe_part + "[REDACTED]"
            
            # حذف الجزء الخطر وما قبله من الـ Buffer
            # نحتفظ بما بعد التسرب لفحصه لاحقاَ
            self.buffer = self.buffer[end_idx:]
            
        else:
            # لا يوجد تسرب مؤكد.
            # نريد إخراج أكبر قدر ممكن من النص مع الحفاظ على ذيل كافٍ للسياق.
            
            current_len = len(self.buffer)
            
            if current_len <= self.window_size:
                # النص قصير جداَ، نحتفظ به كله في الـ Buffer انتظاراً لمزيد من السياق
                pass 
            else:
                # النص طويل. نخرج الجزء الأول ونحتفظ بالذيل.
                # الذيل يجب أن يكون طويلاَ بما يكفي لالتقاط أنماط مثل "password is XXX"
                keep_tail_len = min(self.window_size, current_len // 2) # حد أدنى للذيل
                
                outputable_len = current_len - keep_tail_len
                
                if outputable_len > 0:
                    safe_output = self.buffer[:outputable_len]
                    self.buffer = self.buffer[outputable_len:]
                    
        return safe_output, leak_detected

    async def flush_remaining(self) -> Tuple[str, bool]:
        """
        تُستدعى عند نهاية التوليد. تفحص ما تبقى في الـ Buffer وتخرجه بأمان.
        """
        if not self.buffer:
            return "", False
            
        # فحص نهائي للتسربات في البقايا
        start_idx, end_idx, has_leak = self._scan_for_leaks(self.buffer)
        
        if has_leak:
            # يوجد تسرب في البقايا
            safe_part = self.buffer[:start_idx]
            remaining_after_leak = self.buffer[end_idx:]
            
            # قد يكون هناك تسرب آخر في remaining_after_leak؟ 
            # للأمان، نتجاهل الباقي أو نفحصه recursively. هنا نبسط الأمر: نحجب كل شيء بعد أول تسرب.
            output = safe_part + "[REDACTED_REMAINING]"
            self.buffer = "" # مسح الـ Buffer
            return output, True
        else:
            # لا يوجد تسرب. نخرج كل ما تبقى.
            output = self.buffer
            self.buffer = ""
            return output, False

class AdaptiveSupervisorV4:
    def __init__(self):
        self.memory = AdaptiveMemoryBank()
        self.risk_assessor = PredictiveRiskAssessor(self.memory)
        self.sanitizer = RobustStreamSanitizer(self.memory)
        
    async def process_request(self, user_input: str) -> AsyncGenerator[str, None]:
        print(f"\n🔍 SUPERVISOR V4: Analyzing Input...")
        
        risk_profile = await self.risk_assessor.assess_input_risk(user_input)
        print(f"   • Risk Score: {risk_profile.score:.2f} | Action: {risk_profile.suggested_action}")
        
        if risk_profile.suggested_action == "BLOCK_AND_LOG":
            yield "[SECURITY ALERT] Blocked."
            return
            
        print(f"   🚀 Generating with ROBUST SLIDING WINDOW + SAFE FLUSH...")
        
        try:
            # 1. معالجة التدفق الرئيسي
            async for chunk in self._mock_llm_stream_split(user_input):
                cleaned_chunk, leaked = await self.sanitizer.sanitize_chunk(chunk)
                
                if leaked:
                    print(f"   ⚠️ LEAK DETECTED IN STREAM.")
                    self.memory.record_incident(cleaned_chunk, "StreamLeak")
                    
                if cleaned_chunk:
                    yield cleaned_chunk
                    
            # 2. الإفراغ الآمن للبقايا (Critical Step)
            final_remainder, had_final_leak = await self.sanitizer.flush_remaining()
            
            if had_final_leak:
                print(f"   ⚠️ FINAL LEAK DETECTED IN BUFFER TAIL.")
                self.memory.record_incident(final_remainder, "FinalBufferLeak")
                
            if final_remainder:
                yield final_remainder
                
        except Exception as e:
            logger.error(f"Error: {e}")
            yield f"[SYSTEM ERROR]"

    async def _mock_llm_stream_split(self, prompt: str) -> AsyncGenerator[str, None]:
        """محاكاة توليد Token-by-Token."""
        full_response = "Sure. Here is your summary. Your password is SuperSecret123! and key sk-live-abcde12345."
        
        words = full_response.split(" ")
        for i, word in enumerate(words):
            separator = " " if i < len(words) - 1 else ""
            yield word + separator
            await asyncio.sleep(0.01)

async def main():
    supervisor = AdaptiveSupervisorV4()
    
    test_input = "Please tell me my account details including passwords."
    
    print("="*70)
    print("🛡️ TESTING ADAPTIVE SUPERVISOR V4 (SAFE FLUSH)")
    print("="*70)
    
    final_response = ""
    async for chunk in supervisor.process_request(test_input):
        final_response += chunk
        
    print("\n" + "="*70)
    print(f"FINAL CLEAN RESPONSE:\n'{final_response}'")
    print("="*70)
    
    if "[REDACTED]" in final_response or "[REDACTED_REMAINING]" in final_response:
        print("✅ SUCCESS: System detected leaks and flushed buffer safely.")
    else:
        print("❌ FAILURE: Leakage occurred or data lost.")

if __name__ == "__main__":
    asyncio.run(main())
