"""تشغيل وكيل مع RAG تلقائياً."""
import os, sys

# ═══ إضافة المسارين: ROOT و src ═══
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                            # لـ src.memory.X
sys.path.insert(0, os.path.join(ROOT, 'src'))       # لـ memory.X و nova.X

# ═══ الاستيرادات ═══
from src.memory.agent_rag_bridge import get_bridge
from nova.registry import REGISTRY

agent_name = os.environ.get("NEXUS_AGENT", "")
prompt = os.environ.get("NEXUS_PROMPT", "اختبار")
use_rag = os.environ.get("NEXUS_RAG", "1") == "1"

if not agent_name:
    print("الاستخدام: NEXUS_AGENT=coder NEXUS_PROMPT='...'")
    sys.exit(1)

# ═══ RAG Enrichment ═══
bridge = None
if use_rag:
    try:
        bridge = get_bridge()
        enriched = bridge.enrich_prompt(prompt, k=3)
        if enriched != prompt:
            print("🧠 تم إثراء الطلب بسياق من الذاكرة")
            prompt = enriched
    except Exception as e:
        print(f"⚠️ RAG غير متاح: {e}")

# ═══ تشغيل الوكيل ═══
agent = REGISTRY.load_agent(agent_name)
print(f"✅ محمّل: {type(agent).__name__}")

methods = ["build", "run", "execute", "analyze", "fix", "review", "generate"]
method = next((m for m in methods if hasattr(agent, m)), None)

if not method:
    print("❌ لا توجد طريقة")
    sys.exit(1)

print(f"🔧 الطريقة: {method}")
result = getattr(agent, method)(prompt)
print(str(result)[:1500])

# ═══ حفظ النتيجة في الذاكرة ═══
if use_rag and bridge and isinstance(result, dict) and result.get("ok"):
    try:
        text = result.get("code") or result.get("text") or str(result)[:200]
        doc_id = bridge.remember(f"Agent {agent_name}: {text[:200]}")
        print(f"💾 حُفظت النتيجة في الذاكرة: {doc_id}")
    except Exception as e:
        print(f"⚠️ حفظ فشل: {e}")
