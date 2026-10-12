import logging
from novamind.core.memory import MemoryManager

logger = logging.getLogger("OrchestratorMemory")

class MemoryEnabledPipeline:
    def __init__(self, orchestrator_instance):
        self.orchestrator = orchestrator_instance
        self.memory = MemoryManager(llm_router=orchestrator_instance.llm_router)

    async def run_with_memory(self, session_id: str, user_prompt: str):
        # 1. استرجاع الذكريات الممتدة والخبرات السابقة
        recalled_memories = await self.memory.recall_semantic_memories(user_prompt, top_k=2)
        history = self.memory.get_recent_history(session_id, limit=3)

        context_str = "\n".join([f"- {m['role']}: {m['content']}" for m in recalled_memories])
        
        enriched_prompt = f"""
[Past Relevant Experiences / Memory Context]:
{context_str}

[Current User Request]:
{user_prompt}
"""
        # 2. حفظ طلب المستخدم في الذاكرة
        await self.memory.add_memory(session_id, "user", user_prompt)

        # 3. تشغيل Pipeline المطور
        result = await self.orchestrator.run_pipeline(enriched_prompt)

        # 4. حفظ نتيجة الوكيل الرئيسي في الذاكرة الممتدة
        output_text = str(result.get("primary_output", {}).get("output", ""))
        await self.memory.add_memory(session_id, "agent", output_text, metadata={"routing": result.get("routing_info")})

        return result
