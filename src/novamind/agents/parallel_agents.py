"""
Parallel Agents — True async parallelism with asyncio.
Fixed: Real concurrency + timeout + error isolation.
"""
import asyncio
import logging
import time
from typing import Dict, List, Callable, Any, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("agents.parallel_agents")

# Thread pool for sync → async
_executor = ThreadPoolExecutor(max_workers=8)


class Judge:
    """Evaluates multiple candidates and picks the best."""
    
    def __init__(self):
        self.criteria = ["correctness", "clarity", "efficiency"]
    
    def evaluate(self, candidate: Dict, criteria: Optional[List[str]] = None) -> float:
        """Score a candidate (0-10)."""
        score = 5.0  # baseline
        
        # Simple heuristics
        text = str(candidate.get("output", candidate.get("result", "")))
        
        # Longer = better (usually)
        if len(text) > 100:
            score += 1
        if len(text) > 500:
            score += 1
        
        # No errors
        if candidate.get("ok"):
            score += 2
        else:
            score -= 3
        
        # Has expected keys
        if "content" in candidate or "code" in candidate or "text" in candidate:
            score += 1
        
        return max(0.0, min(10.0, score))
    
    def pick_best(self, candidates: List[Dict]) -> Dict:
        """Return best candidate by score."""
        if not candidates:
            return {"ok": False, "error": "no candidates"}
        
        scored = [(self.evaluate(c), c) for c in candidates]
        scored.sort(reverse=True, key=lambda x: x[0])
        
        best = scored[0][1].copy()
        best["_score"] = scored[0][0]
        return best


class ParallelAgentPool:
    """
    Run multiple agents in parallel with true asyncio.
    Fixed: uses asyncio.gather + timeout + error isolation.
    """
    
    def __init__(self, agents: Dict[str, Callable], timeout: int = 60):
        self.agents = agents
        self.timeout = timeout
    
    async def _run_one(self, name: str, agent: Callable, *args, **kwargs) -> Dict:
        """Run one agent safely with timeout."""
        try:
            loop = asyncio.get_event_loop()
            
            # Run sync agent in executor
            result = await asyncio.wait_for(
                loop.run_in_executor(_executor, lambda: agent(*args, **kwargs)),
                timeout=self.timeout,
            )
            
            return {
                "agent": name,
                "ok": True,
                "result": result,
            }
        except asyncio.TimeoutError:
            return {
                "agent": name,
                "ok": False,
                "error": f"timeout after {self.timeout}s",
            }
        except Exception as e:
            logger.exception(f"agent {name} failed")
            return {
                "agent": name,
                "ok": False,
                "error": str(e)[:200],
            }
    
    async def run_all_async(self, *args, **kwargs) -> Dict[str, Dict]:
        """Run all agents in parallel. Returns {name: result}."""
        tasks = [
            self._run_one(name, agent, *args, **kwargs)
            for name, agent in self.agents.items()
        ]
        
        t0 = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=False)
        elapsed = time.time() - t0
        
        output = {}
        ok_count = 0
        for r in results:
            output[r["agent"]] = r
            if r["ok"]:
                ok_count += 1
        
        logger.info(f"parallel run: {ok_count}/{len(results)} ok in {elapsed:.2f}s")
        return output
    
    def run_all(self, *args, **kwargs) -> Dict[str, Dict]:
        """Sync wrapper for run_all_async."""
        return asyncio.run(self.run_all_async(*args, **kwargs))
    
    def run_best(self, *args, **kwargs) -> Dict:
        """Run all, return best by judge."""
        results = self.run_all(*args, **kwargs)
        candidates = [r["result"] for r in results.values() if r.get("ok") and r.get("result")]
        
        judge = Judge()
        best = judge.pick_best(candidates)
        best["_all_agents"] = list(results.keys())
        return best


class ParallelCoder:
    """
    Generate code candidates from multiple providers,
    pick the best using Judge.
    """
    
    def __init__(self, providers: Optional[List[str]] = None):
        self.providers = providers or ["gemini-1", "groq"]
    
    async def generate_one(self, provider_name: str, prompt: str, system: str = "") -> Dict:
        """Generate from one provider."""
        try:
            from novamind.core.providers.orchestrator import orchestrator
            
            app = orchestrator.apps.get(provider_name)
            if not app:
                return {"ok": False, "error": f"provider {provider_name} not found"}
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _executor,
                lambda: app.call(prompt, task="smart", system=system, max_tokens=2000),
            )
            
            if result.get("ok"):
                result["provider"] = provider_name
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)[:200], "provider": provider_name}
    
    async def generate_async(self, prompt: str, system: str = "") -> Dict:
        """Generate from all providers in parallel."""
        tasks = [self.generate_one(p, prompt, system) for p in self.providers]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        candidates = [r for r in results if r.get("ok")]
        if not candidates:
            return {"ok": False, "error": "all providers failed", "attempts": results}
        
        judge = Judge()
        best = judge.pick_best([{"ok": True, "output": c.get("text", ""), "provider": c.get("provider")} for c in candidates])
        
        # Find matching full result
        for c in candidates:
            if c.get("text") == best.get("output"):
                return {
                    "ok": True,
                    "text": c.get("text", ""),
                    "provider": c.get("provider"),
                    "score": best.get("_score", 0),
                    "candidates_count": len(candidates),
                }
        
        return candidates[0]
    
    def generate(self, prompt: str, system: str = "") -> Dict:
        """Sync wrapper."""
        return asyncio.run(self.generate_async(prompt, system))


# Export
__all__ = ["Judge", "ParallelAgentPool", "ParallelCoder"]

# Auto-instance for registry
parallel_agents = Judge()
