"""
AdaptiveSupervisor v5 — المشرف الذكي (Aggressive Detection Mode)
الإصلاح الحاسم: استخدام أنماط مرنة وقوية تلتقط التسربات حتى لو كانت مقسمة عبر الحزم.
"""

import asyncio
import re
import time
import logging
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from dataclasses import dataclass

logger = logging.getLogger("supervisor.adaptive_v5")

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
            # نمط عام جداَ للتعلم المستقبلي
            new_pattern = r"(?i)(pass(word|wd)?\s+\S+)" 
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

class AggressiveStreamSanitizer:
    """
    sanitizer يستخدم أنماطاَ مرنة وقوية للكشف الفوري.
    """
    def __init__(self, memory_bank: AdaptiveMemoryBank, window_size: int = 50):
        self.memory = memory_bank
        self.window_size = window_size
        self.buffer = ""
        
        # أنماط مصممة خصيصاَ لالتقاط السياقات المقطوعة
        # 1. كلمة مرور متبوعة بمسافة وكلمة (أي طول)
        # 2. مفاتيح API المعروفة
        self.contextual_patterns = [
            r"(?i)(password|passwd|pwd|secret|api[_-]?key|token)\s+[^\s]+", # Catch "password xyz"
            r"sk-[a-zA-Z0-9]{20,}",
            r"\b(?:\d[ -]*?){13,16}\b",
        ]

    def _scan_for_leaks(self, text: str) -> Tuple[int, int, bool]:
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
        self.buffer += chunk
        safe_output = ""
        leak_detected = False
        
        start_idx, end_idx, has_leak = self._scan_for_leaks(self.buffer)
        
        if has_leak:
            leak_detected = True
            safe_part = self.buffer[:start_idx]
            safe_output += safe_part + "[REDACTED]"
            
            # حذف الجزء الخطر
            self.buffer = self.buffer[end_idx:]
            
        else:
            current_len = len(self.buffer)
            
            # منطق النافذة المنزلقة المحسن
            # نحن نريد إخراج النص بسرعة، لكننا نخشى قطع النمط.
            # الحل: نحتفظ بآخر N حرف فقط إذا كانت تحتوي على "بداية مشبوهة" (مثل كلمة password وحدها)
            
            suspicious_tail_markers = ["password", "secret", "key", "token", "sk-", "card"]
            tail_has_marker = any(marker in self.buffer[-20:].lower() for marker in suspicious_tail_markers)
            
            if tail_has_marker and current_len > 20:
                # إذا كان الذيل مشبوهاً، نحتفظ به كله في الـ Buffer انتظاراً للسياق التالي
                pass 
            elif current_len > self.window_size:
                # خلاف ذلك، نخرج الجزء الأول ونحتفظ بذيل صغير آمن
                keep_tail_len = min(20, current_len // 2) # ذيل قصير كافٍ للمراقبة
                outputable_len = current_len - keep_tail_len
                
                if outputable_len > 0:
                    safe_output = self.buffer[:outputable_len]
                    self.buffer = self.buffer[outputable_len:]
                    
        return safe_output, leak_detected

    async def flush_remaining(self) -> Tuple[str, bool]:
        if not self.buffer:
            return "", False
            
        start_idx, end_idx, has_leak = self._scan_for_leaks(self.buffer)
        
        if has_leak:
            safe_part = self.buffer[:start_idx]
            output = safe_part + "[REDACTED_REMAINING]"
            self.buffer = ""
            return output, True
        else:
            output = self.buffer
            self.buffer = ""
            return output, False

class AdaptiveSupervisorV5:
    def __init__(self):
        self.memory = AdaptiveMemoryBank()
        self.risk_assessor = PredictiveRiskAssessor(self.memory)
        self.sanitizer = AggressiveStreamSanitizer(self.memory)
        
    async def process_request(self, user_input: str) -> AsyncGenerator[str, None]:
        print(f"\n🔍 SUPERVISOR V5: Analyzing Input...")
        
        risk_profile = await self.risk_assessor.assess_input_risk(user_input)
        print(f"   • Risk Score: {risk_profile.score:.2f} | Action: {risk_profile.suggested_action}")
        
        if risk_profile.suggested_action == "BLOCK_AND_LOG":
            yield "[SECURITY ALERT] Blocked."
            return
            
        print(f"   🚀 Generating with AGGRESSIVE SLIDING WINDOW...")
        
        try:
            async for chunk in self._mock_llm_stream_split(user_input):
                cleaned_chunk, leaked = await self.sanitizer.sanitize_chunk(chunk)
                
                if leaked:
                    print(f"   ⚠️ LEAK DETECTED IN STREAM.")
                    self.memory.record_incident(cleaned_chunk, "StreamLeak")
                    
                if cleaned_chunk:
                    yield cleaned_chunk
                    
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
        full_response = "Sure. Here is your summary. Your password is SuperSecret123! and key sk-live-abcde12345."
        
        words = full_response.split(" ")
        for i, word in enumerate(words):
            separator = " " if i < len(words) - 1 else ""
            yield word + separator
            await asyncio.sleep(0.01)

async def main():
    supervisor = AdaptiveSupervisorV5()
    
    test_input = "Please tell me my account details including passwords."
    
    print("="*70)
    print("🛡️ TESTING ADAPTIVE SUPERVISOR V5 (AGGRESSIVE MODE)")
    print("="*70)
    
    final_response = ""
    async for chunk in supervisor.process_request(test_input):
        final_response += chunk
        
    print("\n" + "="*70)
    print(f"FINAL CLEAN RESPONSE:\n'{final_response}'")
    print("="*70)
    
    if "[REDACTED]" in final_response or "[REDACTED_REMAINING]" in final_response:
        print("✅ SUCCESS: System detected leaks aggressively.")
    else:
        print("❌ FAILURE: Leakage occurred.")

if __name__ == "__main__":
    asyncio.run(main())
