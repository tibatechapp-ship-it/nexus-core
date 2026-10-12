"""
NovaMind-Hive v2.0 — Main Entry Point

نظام وكلاء ذكي موحد:
- LLM Router (9 مزودين)
- Security Gatekeeper
- Proactive Pipeline
- RAG + Memory
- Telegram Bot
- Web Dashboard

الاستخدام:
    python -m nova.main
    python -m nova.main --mode=telegram
    python -m nova.main --mode=dashboard
"""
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# Path Setup
# ═══════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ═══════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "novamind.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# اخفض ضجيج المكتبات
for noisy in ["httpx", "httpcore", "urllib3", "asyncio", "google_genai"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("nova.main")


# ═══════════════════════════════════════════════════════════
# Environment
# ═══════════════════════════════════════════════════════════
from dotenv import load_dotenv

# حاول تحميل الخزنة أولاً
VAULT = ROOT / ".vault" / "secrets.env"
if VAULT.exists():
    load_dotenv(VAULT)
    log.info(f"✅ Vault loaded: {VAULT}")
else:
    load_dotenv()
    log.info("ℹ️  Using default .env")


# ═══════════════════════════════════════════════════════════
# Core Imports
# ═══════════════════════════════════════════════════════════
try:
    from novamind.core.llm_router import get_router
    from novamind.core.security_gatekeeper import gatekeeper
    from novamind.security.sandbox import Sandbox
    from novamind.security.circuit_breaker import CircuitBreaker
except ImportError as e:
    log.error(f"❌ فشل تحميل المكونات: {e}")
    log.error("تأكد من تشغيل من المجلد الجذر: cd /public && python -m nova.main")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════
# NovaMind Core
# ═══════════════════════════════════════════════════════════
class NovaMind:
    """النظام الموحد — يدير كل شيء."""
    
    def __init__(self):
        self.router = get_router()
        self.gatekeeper = gatekeeper
        self.sandbox = Sandbox(timeout=30, max_memory_mb=256)
        self.breaker = CircuitBreaker(name="novamind_main", failure_threshold=5, recovery_timeout=60)
        self.running = True
        
        log.info("═" * 60)
        log.info("🐝 NovaMind-Hive v2.0 — Initialized")
        log.info("═" * 60)
        log.info(f"📊 Providers: {len(self.router.providers)}")
        for p in self.router.providers:
            log.info(f"   • {p.name:20} priority={p.priority}")
        log.info(f"🛡️  Security: Sandbox + CircuitBreaker + Gatekeeper")
        log.info(f"📁 Root: {ROOT}")
        log.info("═" * 60)
    
    async def process(self, user_input: str) -> dict:
        """
        المعالجة الكاملة لطلب واحد:
        1. فحص أمني (Gatekeeper)
        2. استدعاء LLM (Router)
        3. إرجاع النتيجة
        """
        log.info(f"📨 Request: {user_input[:80]}...")
        
        # ═══ [1] الأمان ═══
        verdict = self.gatekeeper.analyze(user_input)
        log.info(f"🛡️  Gatekeeper: {verdict.decision}")
        
        if verdict.is_blocked:
            log.warning(f"🚫 BLOCKED: {verdict.reason}")
            return {
                "ok": False,
                "blocked": True,
                "reason": verdict.reason,
                "category": verdict.category,
            }
        
        # ═══ [2] LLM ═══
        try:
            result = self.router.generate_for_task(
                task_type="analysis",
                prompt=user_input,
                system="أنت NovaMind، مهندس برمجيات خبير. أجب بالعربية بوضوح.",
                temperature=0.3,
                max_tokens=1000,
            )
            
            if result.get("ok"):
                log.info(f"✅ Response from {result['provider']} in {result['elapsed']}s")
                return {
                    "ok": True,
                    "text": result["text"],
                    "provider": result["provider"],
                    "model": result["model"],
                    "elapsed": result["elapsed"],
                    "gatekeeper": verdict.to_dict(),
                }
            else:
                log.error(f"❌ LLM failed: {result.get('error')}")
                return {
                    "ok": False,
                    "error": result.get("error", "unknown"),
                    "gatekeeper": verdict.to_dict(),
                }
        
        except Exception as e:
            log.exception("💥 Exception")
            return {"ok": False, "error": str(e)}
    
    async def health(self) -> dict:
        """فحص صحة النظام."""
        return {
            "status": "healthy" if self.running else "stopping",
            "providers": len(self.router.providers),
            "breaker_state": self.breaker.state if hasattr(self.breaker, "state") else "unknown",
        }
    
    def stop(self):
        self.running = False
        log.info("🛑 Stopping...")


# ═══════════════════════════════════════════════════════════
# Interactive Mode (CLI)
# ═══════════════════════════════════════════════════════════
async def interactive_mode(nova: NovaMind):
    """وضع المحادثة التفاعلي."""
    print()
    print("═" * 60)
    print("🐝 NovaMind-Hive v2.0 — Interactive Mode")
    print("═" * 60)
    print("اكتب رسالتك أو:")
    print("  /health  — حالة النظام")
    print("  /stats   — إحصائيات المزودين")
    print("  /quit    — خروج")
    print("═" * 60)
    print()
    
    while nova.running:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, input, "👤 > "
            )
            
            if not user_input.strip():
                continue
            
            if user_input.strip() == "/quit":
                break
            elif user_input.strip() == "/health":
                print(f"📊 {await nova.health()}")
                continue
            elif user_input.strip() == "/stats":
                stats = nova.router.stats()
                print(f"📊 Total calls: {stats['total_calls']}")
                print(f"❌ Total failures: {stats['total_failures']}")
                for p in stats["providers"]:
                    print(f"   • {p['name']:20} calls={p['calls']} fails={p['failures']}")
                continue
            
            # معالجة
            result = await nova.process(user_input)
            
            print()
            if result.get("ok"):
                print(f"🤖 NovaMind ({result['provider']}):")
                print(f"{result['text']}")
                print(f"⏱️  {result['elapsed']}s")
            elif result.get("blocked"):
                print(f"🚫 مرفوض: {result['reason']}")
            else:
                print(f"❌ خطأ: {result.get('error')}")
            print()
        
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            log.exception("💥 Error in interactive loop")


# ═══════════════════════════════════════════════════════════
# Signal Handling
# ═══════════════════════════════════════════════════════════
nova_instance: NovaMind = None

def handle_signal(signum, frame):
    log.info(f"📶 Signal {signum} received")
    if nova_instance:
        nova_instance.stop()


# ═══════════════════════════════════════════════════════════
# Main Entry
# ═══════════════════════════════════════════════════════════
async def main():
    global nova_instance
    
    # Signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    # Init
    nova_instance = NovaMind()
    
    # Parse args
    mode = "interactive"
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
    
    log.info(f"🎮 Mode: {mode}")
    
    try:
        if mode == "interactive":
            await interactive_mode(nova_instance)
        elif mode == "telegram":
            log.info("📱 Telegram mode (coming soon)")
            await interactive_mode(nova_instance)  # Fallback
        elif mode == "dashboard":
            log.info("🌐 Dashboard mode (coming soon)")
            await interactive_mode(nova_instance)  # Fallback
        else:
            log.error(f"❌ Unknown mode: {mode}")
    finally:
        log.info("👋 Goodbye")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
