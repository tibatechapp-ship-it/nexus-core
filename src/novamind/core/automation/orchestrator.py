"""
NovaMindOrchestrator — المنسّق الرئيسي 24/7

يشغّل كل الأنظمة معاً:
- Factory Loop (مستمر)
- Health Checker (دوري)
- Auto Scaler (عند الحاجة)
- Intelligence Agency (مستمر)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path
import time
import threading
import signal
import logging
import json

from .factory_loop import FactoryLoop, LoopState
from .health_checker import HealthChecker, HealthStatus
from .auto_scaler import AutoScaler

logger = logging.getLogger("orchestrator")


class OrchestratorState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


class NovaMindOrchestrator:
    """
    المنسّق الرئيسي — يشغّل كل شيء 24/7
    """
    
    def __init__(
        self,
        factory,
        trainer_pool,
        quality_gate,
        bridge,
        commander,
        registry=None,
        guard=None,
        intelligence=None,
        base_dir: Optional[Path] = None,
        cycle_interval: int = 60,
    ):
        self.base_dir = Path(base_dir or Path.cwd())
        
        # الأنظمة
        self.factory = factory
        self.trainer_pool = trainer_pool
        self.quality_gate = quality_gate
        self.bridge = bridge
        self.commander = commander
        self.registry = registry
        self.guard = guard
        self.intelligence = intelligence
        
        # المكونات الفرعية
        self.factory_loop = FactoryLoop(
            factory=factory,
            trainer_pool=trainer_pool,
            quality_gate=quality_gate,
            bridge=bridge,
            commander=commander,
            intelligence=intelligence,
            check_interval=cycle_interval,
            base_dir=self.base_dir,
        )
        
        self.health_checker = HealthChecker(check_interval=30)
        self.auto_scaler = AutoScaler()
        
        # الحالة
        self.state = OrchestratorState.STOPPED
        self.started_at: Optional[float] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # سجل
        self.log_file = self.base_dir / ".nova" / "orchestrator" / "orchestrator.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # إعداد signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("NovaMindOrchestrator initialized")
    
    def _signal_handler(self, signum, frame):
        """معالج الإشارات (Ctrl+C)"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.stop()
    
    # ═══════════════════════════════════════════════════════
    # التحكم
    # ═══════════════════════════════════════════════════════
    
    def start(self):
        """ابدأ كل شيء"""
        if self.state == OrchestratorState.RUNNING:
            logger.warning("Already running")
            return
        
        self.state = OrchestratorState.STARTING
        self.started_at = time.time()
        
        logger.info("=" * 70)
        logger.info("🚀 NovaMind Orchestrator — STARTING 24/7 MODE")
        logger.info("=" * 70)
        
        # 1. سجّل المكونات في الصحة
        self.health_checker.register("factory_loop", self.factory_loop)
        self.health_checker.register("bridge", self.bridge)
        if self.registry:
            self.health_checker.register("registry", self.registry)
        if self.guard:
            self.health_checker.register("guard", self.guard)
        if self.intelligence:
            self.health_checker.register("intelligence", self.intelligence)
        
        # 2. ابدأ Factory Loop
        self.factory_loop.start()
        logger.info("✅ Factory Loop started")
        
        # 3. ابدأ Health Checker
        self.health_checker.start()
        logger.info("✅ Health Checker started")
        
        # 4. ابدأ مراقب المنسّق
        self._stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("✅ Monitor started")
        
        self.state = OrchestratorState.RUNNING
        
        logger.info("=" * 70)
        logger.info("✅ NovaMind 24/7 RUNNING")
        logger.info("=" * 70)
        self._log("STARTED 24/7")
    
    def stop(self):
        """أوقف كل شيء بشكل آمن"""
        if self.state in (OrchestratorState.STOPPED, OrchestratorState.STOPPING):
            return
        
        self.state = OrchestratorState.STOPPING
        logger.info("🛑 Stopping Orchestrator...")
        
        # أوقف المراقب
        self._stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        # أوقف المكونات
        self.health_checker.stop()
        self.factory_loop.stop()
        
        self.state = OrchestratorState.STOPPED
        
        logger.info("✅ Orchestrator stopped cleanly")
        self._log("STOPPED")
    
    def pause(self):
        """أوقف مؤقتاً"""
        self.state = OrchestratorState.PAUSED
        self.factory_loop.pause()
        logger.info("⏸️ Orchestrator PAUSED")
    
    def resume(self):
        """استأنف"""
        self.state = OrchestratorState.RUNNING
        self.factory_loop.resume()
        logger.info("▶️ Orchestrator RESUMED")
    
    # ═══════════════════════════════════════════════════════
    # المراقب الرئيسي
    # ═══════════════════════════════════════════════════════
    
    def _monitor_loop(self):
        """حلقة المراقبة الرئيسية"""
        while not self._stop_event.is_set():
            try:
                if self.state == OrchestratorState.RUNNING:
                    self._monitor_cycle()
                
                if self._stop_event.wait(timeout=60):  # كل دقيقة
                    break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                time.sleep(5)
        
        logger.info("Monitor loop exited")
    
    def _monitor_cycle(self):
        """دورة مراقبة واحدة"""
        # 1. افحص الصحة
        health = self.health_checker.stats()
        
        # 2. قيّم الحاجة للتوسيع
        metrics = self._collect_metrics()
        scaling = self.auto_scaler.evaluate(metrics)
        
        # 3. إذا احتجنا وكلاء إضافيين، ضاعف الطلب
        if scaling["action"] == "scale_up":
            logger.info(f"⚖️ Scaler: {scaling['reason']}")
        
        # 4. اطبع حالة دورية
        uptime = time.time() - self.started_at
        logger.info(
            f"[Monitor] uptime={uptime/3600:.1f}h "
            f"health={health.get('overall_health', 'unknown')} "
            f"cycles={self.factory_loop.cycle_count}"
        )
    
    def _collect_metrics(self) -> Dict:
        """اجمع المقاييس"""
        return {
            "queue_length": 0,  # TODO: من Queue Manager
            "avg_response_time": 5.0,
            "utilization": 0.5,
            "active_agents": len(self.registry.profiles) if self.registry else 0,
        }
    
    # ═══════════════════════════════════════════════════════
    # السجل والإحصائيات
    # ═══════════════════════════════════════════════════════
    
    def _log(self, message: str):
        """اكتب في السجل"""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass
    
    def stats(self) -> Dict:
        """إحصائيات شاملة"""
        uptime = time.time() - self.started_at if self.started_at else 0
        
        return {
            "state": self.state.value,
            "uptime_hours": round(uptime / 3600, 2),
            "factory_loop": self.factory_loop.stats(),
            "health": self.health_checker.stats(),
            "scaler": self.auto_scaler.stats(),
        }
    
    def wait(self):
        """انتظر حتى التوقف (للـ main thread)"""
        try:
            while self.state == OrchestratorState.RUNNING:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
