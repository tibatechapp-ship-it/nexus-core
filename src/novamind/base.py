"""BaseAgent — Stable Version with Sync SQLite Memory."""
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from novamind.memory.engine import get_memory_engine

log = logging.getLogger("BaseAgent")

class BaseAgent(ABC):
    NAME: str = "base"
    DESCRIPTION: str = ""
    ROLE: str = "worker"
    LEVEL: int = 1
    CAPABILITIES: List[str] = []
    
    def __init__(self):
        self.memory = get_memory_engine()
        self.stats = {"total": 0, "success": 0, "failed": 0}

    @abstractmethod
    async def handle(self, task: Dict[str, Any]) -> Dict[str, Any]:
        pass

    async def execute_with_memory(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task with automatic memory retrieval and storage."""
        action = task.get("action", "")
        params = task.get("params", {})
        
        # 1. Retrieve Context (Direct Call - No Thread Needed anymore)
        query_str = f"{action} {str(params)[:100]}"
        
        try:
            # Direct synchronous call
            past_experiences = self.memory.retrieve_similar_experiences(
                query=query_str,
                agent_name=self.NAME,
                top_k=2
            )
            
            if past_experiences:
                task["_memory_context"] = [exp["content"] for exp in past_experiences]
                log.info(f"🧠 Injected {len(past_experiences)} memories into {self.NAME}")
            else:
                task["_memory_context"] = []
                
        except Exception as e:
            log.warning(f"Memory retrieval failed: {e}")
            task["_memory_context"] = []

        # 2. Execute Core Logic
        start_time = asyncio.get_event_loop().time()
        try:
            result = await self.handle(task)
            duration = asyncio.get_event_loop().time() - start_time
            
            # 3. Update Stats
            success = result.get("ok", False)
            self.stats["total"] += 1
            if success:
                self.stats["success"] += 1
            else:
                self.stats["failed"] += 1
                
            # 4. Store Experience (Fire and Forget using create_task for non-blocking write)
            summary = str(result.get("result", ""))[:100]
            insight = "Success" if success else f"Error: {result.get('error', 'Unknown')}"
            
            # We use asyncio.create_task to schedule the sync function execution 
            # without blocking the current coroutine, effectively making it "fire-and-forget"
            # Note: Since store_experience is now sync, we can just call it directly 
            # OR wrap it in a thread if we want true non-blocking IO. 
            # For simplicity and speed with SQLite local files, direct call is fine 
            # but let's keep it clean by calling it directly since it's fast.
            
            self.memory.store_experience(
                agent_name=self.NAME,
                task_description=f"{action}: {str(params)[:50]}",
                result_summary=insight,
                success=success,
                tags=[self.ROLE]
            )
            
            return result

        except Exception as e:
            self.stats["total"] += 1
            self.stats["failed"] += 1
            # Store failure
            self.memory.store_experience(
                agent_name=self.NAME,
                task_description=f"{action}: {str(params)[:50]}",
                result_summary=f"Exception: {str(e)}",
                success=False,
                tags=[self.ROLE]
            )
            raise e

    def get_capabilities(self) -> List[str]:
        return self.CAPABILITIES
    
    def status(self) -> Dict[str, Any]:
        return {
            "name": self.NAME,
            "role": self.ROLE,
            "level": self.LEVEL,
            "description": self.DESCRIPTION,
            "stats": self.stats,
            "capabilities": self.CAPABILITIES
        }
