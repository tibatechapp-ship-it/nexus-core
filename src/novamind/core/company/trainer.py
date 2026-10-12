"""Agent Trainer - يدرب الوكلاء."""
import asyncio
import logging
import time
from typing import Dict, List, Any
import sys
# [FIXED PATH] Use relative imports or conftest.py instead

from novamind.core.company.test_bank import TestBank
from novamind.core.company.prompts import get_prompt

logger = logging.getLogger("Trainer")


class AgentTrainer:
    def __init__(self, supreme):
        self.supreme = supreme
        self.bank = TestBank()
        self.results: List[Dict] = []
    
    async def train_soldier(self, soldier_id: str, count: int = 3) -> Dict[str, Any]:
        soldier = next((s for s in self.supreme.soldiers if s.id == soldier_id), None)
        if not soldier:
            return {"status": "not_found", "soldier_id": soldier_id}
        
        tests = self.bank.get_tests(soldier.specialty, soldier.rank.name, count)
        if not tests:
            return {"status": "no_tests", "specialty": soldier.specialty}
        
        logger.info(f"Training {soldier_id} ({soldier.specialty}) with {len(tests)} tests")
        
        results = []
        for test in tests:
            t0 = time.time()
            try:
                # استخدم prompt محسّن
                soldier.system_prompt = get_prompt(soldier.specialty)
                result = await self.supreme.execute_mission(soldier.specialty, test["task"])
                dt = time.time() - t0
                success = result.get("status") == "success"
                results.append({
                    "test_id": test["id"],
                    "task": test["task"][:80],
                    "success": success,
                    "duration": round(dt, 2),
                })
                if success:
                    self.supreme.memory.record_lesson(
                        specialty=soldier.specialty,
                        task=test["task"],
                        response=result.get("response", "")[:500],
                        success=True,
                        agent_id=soldier_id,
                    )
            except Exception as e:
                logger.error(f"Test failed: {e}")
                results.append({"test_id": test["id"], "success": False, "error": str(e)[:100]})
        
        self.supreme.audit.record("training", soldier_id, {
            "tests_run": len(results),
            "success": sum(1 for r in results if r.get("success")),
        })
        
        summary = {
            "status": "trained",
            "soldier_id": soldier_id,
            "specialty": soldier.specialty,
            "rank": soldier.rank.name,
            "tests_run": len(results),
            "success": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "results": results,
        }
        self.results.append(summary)
        return summary
    
    async def train_all(self, count_per_soldier: int = 2, max_soldiers: int = None) -> Dict[str, Any]:
        soldiers = self.supreme.soldiers
        if max_soldiers:
            soldiers = soldiers[:max_soldiers]
        
        logger.info(f"Training {len(soldiers)} soldiers")
        t0 = time.time()
        summaries = []
        for i, soldier in enumerate(soldiers, 1):
            summary = await self.train_soldier(soldier.id, count=count_per_soldier)
            summaries.append(summary)
            if i % 5 == 0:
                logger.info(f"Progress: {i}/{len(soldiers)}")
        
        dt = time.time() - t0
        total_tests = sum(s.get("tests_run", 0) for s in summaries)
        total_success = sum(s.get("success", 0) for s in summaries)
        
        return {
            "status": "done",
            "soldiers_trained": len(summaries),
            "total_tests": total_tests,
            "total_success": total_success,
            "total_failed": total_tests - total_success,
            "pass_rate": round(total_success / max(total_tests, 1), 3),
            "total_time": round(dt, 1),
        }
