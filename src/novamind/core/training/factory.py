"""
AgentFactory — مصنع خلق الوكلاء تلقائياً

المسؤوليات:
- استلام طلبات من القائد (ناقص وكيل بمهارة X)
- تصميم وكيل جديد حسب الطلب
- تدريبه واختباره
- تسليمه جاهزاً
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path
import uuid
import time
import json
import logging

logger = logging.getLogger("factory")


class AgentSpec(Enum):
    """أنواع الوكلاء"""
    CODER = "coder"
    ANALYZER = "analyzer"
    FIXER = "fixer"
    TESTER = "tester"
    SECURITY = "security"
    DEVOPS = "devops"
    QUALITY = "quality"
    LEARNER = "learner"


@dataclass
class AgentBlueprint:
    """مخطط وكيل جديد"""
    spec: AgentSpec
    name: str
    skills: List[str]
    domain: str
    level: int = 1
    isolation: str = "strict"
    max_concurrent: int = 1
    priority: int = 5
    rationale: str = ""  # لماذا خُلِق؟


@dataclass
class AgentOrder:
    """طلب إنشاء وكيل"""
    order_id: str
    requested_by: str  # القائد
    spec: AgentSpec
    domain: str
    urgency: int  # 1-5 (5 الأكثر إلحاحاً)
    required_skills: List[str] = field(default_factory=list)
    created_at: float = 0.0
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()


@dataclass
class AgentProduct:
    """وكيل جاهز بعد التصنيع"""
    agent_id: str
    blueprint: AgentBlueprint
    trained_at: float
    tests_passed: int
    tests_total: int
    is_ready: bool
    metadata: Dict = field(default_factory=dict)


class AgentFactory:
    """
    المصنع — يخلق وكلاء جدد عند الطلب
    
    العملية:
    1. استلام الطلب من القائد
    2. تصميم blueprint
    3. تسليم للمدرب المتخصص
    4. التدريب والاختبار
    5. تسليم جاهز
    """
    
    def __init__(self, base_dir: Path, realm_manager):
        self.base_dir = base_dir / "training" / "factory"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.realm_manager = realm_manager
        
        # طابور الطلبات
        self.orders_queue: List[AgentOrder] = []
        self.active_orders: Dict[str, AgentOrder] = {}
        self.completed_orders: List[Dict] = []
        
        # عدادات
        self.total_created = 0
        self.total_failed = 0
        
        logger.info("AgentFactory initialized")
    
    def receive_order(self, order: AgentOrder) -> str:
        """استلام طلب إنشاء وكيل"""
        self.orders_queue.append(order)
        self.active_orders[order.order_id] = order
        
        # رتّب حسب الأولوية
        self.orders_queue.sort(key=lambda o: (-o.urgency, o.created_at))
        
        logger.info(f"Order received: {order.order_id} ({order.spec.value}) urgency={order.urgency}")
        return order.order_id
    
    def design_blueprint(self, order: AgentOrder) -> AgentBlueprint:
        """تصميم مخطط الوكيل حسب الطلب"""
        # قواعد التصميم
        name = f"{order.spec.value}_agent_{self.total_created + 1:04d}"
        
        # المهارات الافتراضية حسب النوع
        default_skills = {
            AgentSpec.CODER: ["write_function", "write_class", "refactor"],
            AgentSpec.ANALYZER: ["detect_bugs", "assess_quality", "estimate_complexity"],
            AgentSpec.FIXER: ["fix_syntax", "fix_logic", "fix_performance"],
            AgentSpec.TESTER: ["run_tests", "generate_test_cases", "measure_coverage"],
            AgentSpec.SECURITY: ["detect_vulnerabilities", "audit_secrets", "scan_deps"],
            AgentSpec.DEVOPS: ["build_docker", "deploy_k8s", "monitor"],
            AgentSpec.QUALITY: ["review_code", "measure_metrics", "enforce_standards"],
            AgentSpec.LEARNER: ["extract_lessons", "update_knowledge", "detect_patterns"],
        }
        
        skills = order.required_skills or default_skills.get(order.spec, ["basic_skill"])
        
        return AgentBlueprint(
            spec=order.spec,
            name=name,
            skills=skills,
            domain=order.domain,
            level=1,  # يبدأ مبتدئاً
            priority=max(1, 6 - order.urgency),
            rationale=f"Requested by {order.requested_by} for {order.domain}",
        )
    
    def spawn(self, blueprint: AgentBlueprint) -> AgentProduct:
        """
        إنشاء وكيل جديد فعلياً
        
        في التنفيذ الكامل، هذه الدالة:
        1. تختار مدرباً متخصصاً
        2. تُرسل الـ blueprint
        3. تنتظر انتهاء التدريب
        4. تستلم المنتج
        """
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        
        logger.info(f"Spawning: {blueprint.name} ({blueprint.spec.value})")
        
        # في الواقع: تدريب حقيقي
        # هنا: محاكاة
        time.sleep(0.1)
        
        product = AgentProduct(
            agent_id=agent_id,
            blueprint=blueprint,
            trained_at=time.time(),
            tests_passed=5,
            tests_total=5,
            is_ready=True,
            metadata={
                "created_by": "factory",
                "training_hours": 0,
            }
        )
        
        self.total_created += 1
        logger.info(f"  ✓ Agent {agent_id} ready")
        
        return product
    
    def process_next_order(self) -> Optional[AgentProduct]:
        """معالجة الطلب التالي في الطابور"""
        if not self.orders_queue:
            return None
        
        order = self.orders_queue.pop(0)
        logger.info(f"Processing order: {order.order_id}")
        
        try:
            blueprint = self.design_blueprint(order)
            product = self.spawn(blueprint)
            
            self.completed_orders.append({
                "order_id": order.order_id,
                "agent_id": product.agent_id,
                "completed_at": time.time(),
                "success": True,
            })
            
            del self.active_orders[order.order_id]
            return product
        
        except Exception as e:
            self.total_failed += 1
            logger.error(f"Order {order.order_id} failed: {e}")
            self.completed_orders.append({
                "order_id": order.order_id,
                "completed_at": time.time(),
                "success": False,
                "error": str(e),
            })
            return None
    
    def status(self) -> Dict:
        return {
            "queued": len(self.orders_queue),
            "active": len(self.active_orders),
            "completed": len(self.completed_orders),
            "total_created": self.total_created,
            "total_failed": self.total_failed,
        }
