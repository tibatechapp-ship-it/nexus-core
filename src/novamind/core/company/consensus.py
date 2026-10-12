"""Consensus Layer - 3 وكلاء يصوّتون على القرارات الحرجة."""
import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Dict, List, Any, Optional

from novamind.core.llm_router import LLMRouter

logger = logging.getLogger("Consensus")


class ConsensusVote:
    """يقرر عبر 3 وكلاء بالتوازي."""
    
    def __init__(self, llm_router: Optional[LLMRouter] = None, quorum: int = 2):
        self.llm = llm_router or LLMRouter()
        self.quorum = quorum  # عدد الأصوات المطلوبة (افتراضي 2 من 3)
        self.history: List[Dict] = []
    
    def _similarity(self, a: str, b: str) -> float:
        """تشابه بسيط بين نصين (0.0 - 1.0)."""
        a_tokens = set(re.findall(r'\w+', a.lower()))
        b_tokens = set(re.findall(r'\w+', b.lower()))
        if not a_tokens or not b_tokens:
            return 0.0
        common = a_tokens & b_tokens
        return len(common) / max(len(a_tokens), len(b_tokens))
    
    async def _ask_voter(self, voter_id: str, task: str, system_prompt: str) -> Dict:
        """يسأل مصوّتاً واحداً."""
        t0 = time.time()
        try:
            response = await asyncio.wait_for(
                self.llm.generate(task, system_prompt=system_prompt),
                timeout=180.0,
            )
            return {
                "voter": voter_id,
                "response": response,
                "success": True,
                "time": round(time.time() - t0, 2),
            }
        except Exception as e:
            return {
                "voter": voter_id,
                "response": "",
                "success": False,
                "error": str(e),
                "time": round(time.time() - t0, 2),
            }
    
    async def vote(
        self,
        task: str,
        voter_prompts: List[str],
        similarity_threshold: float = 0.5,
    ) -> Dict[str, Any]:
        """يصوّت 3 وكلاء على مهمة."""
        voters_count = len(voter_prompts)
        if voters_count < 2:
            return {"error": "Need at least 2 voters"}
        
        logger.info(f"Consensus: asking {voters_count} voters...")
        
        # 1. اسأل الجميع بالتوازي
        tasks = [
            self._ask_voter(f"V{i+1}", task, prompt)
            for i, prompt in enumerate(voter_prompts)
        ]
        votes = await asyncio.gather(*tasks)
        
        # 2. احسب التشابهات
        successful = [v for v in votes if v["success"]]
        if len(successful) < self.quorum:
            result = {
                "decision": "NO_CONSENSUS",
                "reason": f"Only {len(successful)}/{voters_count} succeeded",
                "votes": votes,
            }
            self.history.append(result)
            return result
        
        # 3. ابحث عن مجموعة متوافقة
        clusters = []
        used = set()
        for i, v1 in enumerate(successful):
            if i in used:
                continue
            cluster = [v1]
            used.add(i)
            for j, v2 in enumerate(successful):
                if j <= i or j in used:
                    continue
                sim = self._similarity(v1["response"], v2["response"])
                if sim >= similarity_threshold:
                    cluster.append(v2)
                    used.add(j)
            clusters.append(cluster)
        
        # 4. أفضل مجموعة
        clusters.sort(key=len, reverse=True)
        best_cluster = clusters[0] if clusters else []
        
        if len(best_cluster) >= self.quorum:
            # اتفاق
            winner = max(best_cluster, key=lambda v: len(v["response"]))
            result = {
                "decision": "CONSENSUS",
                "winner": winner["voter"],
                "response": winner["response"],
                "voted_by": [v["voter"] for v in best_cluster],
                "total_voters": voters_count,
                "similarity_avg": round(
                    sum(self._similarity(winner["response"], v["response"]) 
                        for v in best_cluster) / len(best_cluster), 3
                ),
                "votes": votes,
            }
        else:
            # لا اتفاق
            result = {
                "decision": "NO_CONSENSUS",
                "reason": f"Max cluster size {len(best_cluster)} < quorum {self.quorum}",
                "votes": votes,
            }
        
        self.history.append(result)
        logger.info(f"Consensus: {result['decision']}")
        return result
    
    def stats(self) -> Dict[str, Any]:
        if not self.history:
            return {"votes": 0}
        consensus_count = sum(1 for h in self.history if h["decision"] == "CONSENSUS")
        return {
            "votes": len(self.history),
            "consensus": consensus_count,
            "no_consensus": len(self.history) - consensus_count,
            "success_rate": round(consensus_count / len(self.history), 3),
        }
    
    async def close(self):
        await self.llm.close()
