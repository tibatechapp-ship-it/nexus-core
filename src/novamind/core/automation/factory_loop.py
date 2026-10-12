"""
FactoryLoop — المصنع الديناميكي المستمر

يعمل 24/7:
1. يفحص الحاجة كل X دقيقة
2. إذا وجد نقصاً → يُنتج
3. يختبر ويضمن الجودة
4. يسلّم للقائد
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path
import time
import threading
import logging
import json
import random

logger = logging.getLogger("factory_loop")


class LoopState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


@dataclass
class ProductionCycle:
    """دورة إنتاج واحدة"""
    cycle_id: int
    started_at: float
    ended_at: float = 0.0
    gaps_detected: int = 0
    agents_requested: int = 0
    agents_created: int = 0
    agents_delivered: int = 0
    agents_failed: int = 0
    duration: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration": self.duration,
            "gaps": self.gaps_detected,
            "requested": self.agents_requested,
            "created": self.agents_created,
            "delivered": self.agents_delivered,
            "failed": self.agents_failed,
        }


class FactoryLoop:
    """
    المصنع الديناميكي
    
    - يعمل في thread منفصل
    - يفحص الحاجة بشكل دوري
    - يُنتج عند الحاجة فقط (ديناميكي)
    """
    
    # إعدادات افتراضية
    DEFAULT_CHECK_INTERVAL = 60      # ثانية — يفحص كل دقيقة
    DEFAULT_MAX_PER_CYCLE = 5        # أقصى إنتاج في الدورة
    DEFAULT_GAP_THRESHOLD = 3        # عتبة النقص
    DEFAULT_HOURS = (0, 24)          # ساعات العمل (24/7)
    
    def __init__(
        self,
        factory,
        trainer_pool,
        quality_gate,
        bridge,
        commander,
        intelligence=None,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        max_per_cycle: int = DEFAULT_MAX_PER_CYCLE,
        gap_threshold: int = DEFAULT_GAP_THRESHOLD,
        base_dir: Optional[Path] = None,
    ):
        self.factory = factory
        self.trainer_pool = trainer_pool
        self.quality_gate = quality_gate
        self.bridge = bridge
        self.commander = commander
        self.intelligence = intelligence
        
        self.check_interval = check_interval
        self.max_per_cycle = max_per_cycle
        self.gap_threshold = gap_threshold
        self.base_dir = base_dir
        
        # الحالة
        self.state = LoopState.STOPPED
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # إحصائيات
        self.cycle_count = 0
        self.cycles: List[ProductionCycle] = []
        self.total_created = 0
        self.total_delivered = 0
        self.total_failed = 0
        self.started_at: Optional[float] = None
        
        # سجل
        self.base_dir = base_dir or Path.cwd()
        self.log_file = self.base_dir / ".nova" / "factory" / "loop.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"FactoryLoop initialized (interval={check_interval}s, max={max_per_cycle})")
    
    # ═══════════════════════════════════════════════════════
    # التحكم
    # ═══════════════════════════════════════════════════════
    
    def start(self):
        """ابدأ الحلقة"""
        if self.state == LoopState.RUNNING:
            logger.warning("FactoryLoop already running")
            return
        
        self._stop_event.clear()
        self.state = LoopState.RUNNING
        self.started_at = time.time()
        
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        
        logger.info("🏭 FactoryLoop STARTED (24/7 mode)")
        self._log("STARTED")
    
    def stop(self, timeout: int = 5):
        """أوقف الحلقة"""
        if self.state != LoopState.RUNNING:
            return
        
        logger.info("Stopping FactoryLoop...")
        self._stop_event.set()
        self.state = LoopState.STOPPED
        
        if self.thread:
            self.thread.join(timeout=timeout)
        
        logger.info("🏭 FactoryLoop STOPPED")
        self._log("STOPPED")
    
    def pause(self):
        """أوقف مؤقتاً"""
        self.state = LoopState.PAUSED
        logger.info("⏸️ FactoryLoop PAUSED")
    
    def resume(self):
        """استأنف"""
        self.state = LoopState.RUNNING
        logger.info("▶️ FactoryLoop RESUMED")
    
    # ═══════════════════════════════════════════════════════
    # الحلقة الرئيسية
    # ═══════════════════════════════════════════════════════
    
    def _run_loop(self):
        """الحلقة الرئيسية"""
        while not self._stop_event.is_set():
            try:
                if self.state == LoopState.RUNNING:
                    self._run_one_cycle()
                
                # انتظر
                if self._stop_event.wait(timeout=self.check_interval):
                    break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                self._log(f"ERROR: {e}")
                time.sleep(5)
        
        logger.info("Loop exited")
    
    def _run_one_cycle(self):
        """دورة واحدة"""
        self.cycle_count += 1
        cycle = ProductionCycle(
            cycle_id=self.cycle_count,
            started_at=time.time(),
        )
        
        try:
            # 1. فحص الحاجة
            gaps = self._detect_gaps()
            cycle.gaps_detected = len(gaps)
            
            if not gaps:
                logger.info(f"Cycle {self.cycle_count}: no gaps, sleeping...")
                cycle.ended_at = time.time()
                cycle.duration = cycle.ended_at - cycle.started_at
                self.cycles.append(cycle)
                return
            
            # 2. أولويات
            gaps.sort(key=lambda g: -g.get("urgency", 0))
            gaps = gaps[:self.max_per_cycle]
            cycle.agents_requested = len(gaps)
            
            logger.info(f"Cycle {self.cycle_count}: {len(gaps)} gaps detected")
            
            # 3. اطلب وأنتج
            for gap in gaps:
                self._produce_for_gap(gap, cycle)
            
            # 4. أنهِ
            cycle.ended_at = time.time()
            cycle.duration = cycle.ended_at - cycle.started_at
            self.cycles.append(cycle)
            
            logger.info(
                f"Cycle {self.cycle_count} done: "
                f"created={cycle.agents_created}, "
                f"delivered={cycle.agents_delivered}, "
                f"failed={cycle.agents_failed}"
            )
        
        except Exception as e:
            logger.error(f"Cycle {self.cycle_count} error: {e}")
            cycle.ended_at = time.time()
            cycle.duration = cycle.ended_at - cycle.started_at
            self.cycles.append(cycle)
    
    def _detect_gaps(self) -> List[Dict]:
        """اكتشف الفجوات"""
        # استخدم القائد
        if hasattr(self.commander, "analyze_gaps"):
            gaps = self.commander.analyze_gaps()
            # فلتر بالفجوات الحقيقية
            return [g for g in gaps if g.get("urgency", 0) >= 3]
        return []
    
    def _produce_for_gap(self, gap: Dict, cycle: ProductionCycle):
        """أنتج وكيلاً لفجوة معينة"""
        try:
            domain = gap["domain"]
            urgency = gap.get("urgency", 3)
            
            # 1. اطلب من المصنع
            spec = self._spec_for_domain(domain)
            
            # 2. أنشئ Blueprint
            from novamind.core.training.factory import AgentOrder, AgentSpec
            order = AgentOrder(
                order_id=f"auto_{int(time.time())}_{random.randint(1000, 9999)}",
                requested_by="factory_loop",
                spec=AgentSpec(spec),
                domain=domain,
                urgency=urgency,
                required_skills=self._skills_for_domain(domain),
            )
            
            blueprint = self.factory.design_blueprint(order)
            
            # 3. درّب
            train_result = self.trainer_pool.assign_training(blueprint)
            
            if not train_result or not train_result.get("ok"):
                cycle.agents_failed += 1
                logger.warning(f"Training failed: {train_result}")
                return
            
            # 4. أنشئ المنتج
            product = self.factory.spawn(blueprint)
            cycle.agents_created += 1
            self.total_created += 1
            
            # 5. افحص الجودة
            quality_result = self.quality_gate.evaluate(
                product.agent_id,
                {"spec": spec, "trainer_quality": 0.88},
            )
            
            if quality_result["verdict"] == "passed":
                # 6. سلّم
                self.bridge.deliver_agent("factory_loop", {
                    "agent_id": product.agent_id,
                    "blueprint": {
                        "name": blueprint.name,
                        "spec": spec,
                        "domain": domain,
                        "skills": blueprint.skills,
                    },
                    "quality_score": quality_result["weighted_score"],
                })
                cycle.agents_delivered += 1
                self.total_delivered += 1
                logger.info(f"✅ Delivered {product.agent_id} ({spec}, score={quality_result['weighted_score']})")
            
            elif quality_result["verdict"] == "needs_retraining":
                logger.warning(f"⚠️ {product.agent_id} needs retraining")
                cycle.agents_failed += 1
                self.total_failed += 1
            
            else:
                logger.error(f"❌ {product.agent_id} failed quality gate")
                cycle.agents_failed += 1
                self.total_failed += 1
        
        except Exception as e:
            cycle.agents_failed += 1
            self.total_failed += 1
            logger.error(f"Produce error: {e}")
    
    def _spec_for_domain(self, domain: str) -> str:
        """حدد نوع الوكيل حسب المجال"""
        mapping = {
            "coding": "coder",
            "security": "security",
            "devops": "devops",
            "quality": "quality",
            "database": "coder",
            "frontend": "coder",
            "backend": "coder",
            "testing": "tester",
            "ai": "learner",
            "architecture": "analyzer",
        }
        return mapping.get(domain, "coder")
    
    def _skills_for_domain(self, domain: str) -> List[str]:
        """مهارات مطلوبة حسب المجال"""
        skills = {
            "coding": ["write_function", "write_class", "refactor"],
            "security": ["detect_vulnerabilities", "audit_secrets"],
            "devops": ["build_docker", "deploy_k8s"],
            "quality": ["review_code", "measure_metrics"],
            "database": ["write_sql", "optimize_query"],
        }
        return skills.get(domain, ["basic"])
    
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
        """إحصائيات المصنع"""
        uptime = time.time() - self.started_at if self.started_at else 0
        
        return {
            "state": self.state.value,
            "uptime_hours": round(uptime / 3600, 2),
            "cycles_completed": self.cycle_count,
            "total_created": self.total_created,
            "total_delivered": self.total_delivered,
            "total_failed": self.total_failed,
            "success_rate": round(
                self.total_delivered / self.total_created, 3
            ) if self.total_created else 0.0,
            "avg_cycle_duration": round(
                sum(c.duration for c in self.cycles) / len(self.cycles), 2
            ) if self.cycles else 0.0,
            "last_10_cycles": [c.to_dict() for c in self.cycles[-10:]],
        }
