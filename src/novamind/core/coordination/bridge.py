"""
CoordinationBridge — الجسر الوحيد بين النظامين

يسمح فقط بـ:
1. Commander → Training: طلب وكيل جديد
2. Training → Commander: تسليم وكيل جاهز
3. Training → Commander: تقرير إحصائي
4. لا شيء آخر!

يمنع تماماً:
- العاملون من رؤية المدربين
- المدربون من رؤية العاملين
- تبادل المعلومات غير الضروري
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from queue import Queue
import time
import uuid
import logging

logger = logging.getLogger("bridge")


class BridgeMessageType(Enum):
    REQUEST_AGENT = "request_agent"          # Commander → Training
    AGENT_DELIVERED = "agent_delivered"      # Training → Commander
    TRAINING_STATS = "training_stats"        # Training → Commander
    URGENT_ORDER = "urgent_order"            # Commander → Training (عاجل)
    QUALITY_ALERT = "quality_alert"          # Training → Commander (تنبيه)


@dataclass
class BridgeMessage:
    """رسالة عبر الجسر"""
    msg_id: str = ""
    msg_type: BridgeMessageType = BridgeMessageType.REQUEST_AGENT
    sender: str = ""
    recipient: str = ""
    payload: Any = None
    requires_ack: bool = False
    timestamp: float = 0.0
    
    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = f"bm_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = time.time()


class CoordinationBridge:
    """
    الجسر الحصري بين العمليات والتدريب
    """
    
    def __init__(self):
        # طابوران فقط (اتجاهان)
        self.to_training: Queue = Queue()      # من Commander → Training
        self.to_commander: Queue = Queue()     # من Training → Commander
        
        # سجل
        self.history: List[BridgeMessage] = []
        self.pending_requests: Dict[str, BridgeMessage] = {}
        
        # إحصائيات
        self.stats = {
            "requests_sent": 0,
            "agents_delivered": 0,
            "errors": 0,
        }
        
        logger.info("CoordinationBridge ready")
    
    # ─── من القائد إلى التدريب ───
    
    def request_agent(self, commander_id: str, spec: Dict) -> str:
        """طلب وكيل جديد من التدريب"""
        msg = BridgeMessage(
            msg_type=BridgeMessageType.REQUEST_AGENT,
            sender=commander_id,
            recipient="training_factory",
            payload=spec,
            requires_ack=True,
        )
        
        self.to_training.put(msg)
        self.pending_requests[msg.msg_id] = msg
        self.history.append(msg)
        self.stats["requests_sent"] += 1
        
        logger.info(f"[BRIDGE] Request → Training: {spec.get('spec')} (urgency={spec.get('urgency')})")
        return msg.msg_id
    
    def urgent_order(self, commander_id: str, spec: Dict) -> str:
        """طلب عاجل (يتجاوز الطابور)"""
        msg = BridgeMessage(
            msg_type=BridgeMessageType.URGENT_ORDER,
            sender=commander_id,
            recipient="training_factory",
            payload={**spec, "urgent": True},
            requires_ack=True,
        )
        
        # ضعه في مقدمة الطابور (نستخدم list مؤقتاً)
        self.to_training.queue.insert(0, msg) if hasattr(self.to_training, 'queue') else self.to_training.put(msg)
        self.pending_requests[msg.msg_id] = msg
        self.history.append(msg)
        self.stats["requests_sent"] += 1
        
        logger.info(f"[BRIDGE] URGENT → Training: {spec.get('spec')}")
        return msg.msg_id
    
    # ─── من التدريب إلى القائد ───
    
    def deliver_agent(self, trainer_id: str, product: Dict) -> str:
        """تسليم وكيل جاهز للقائد"""
        msg = BridgeMessage(
            msg_type=BridgeMessageType.AGENT_DELIVERED,
            sender=trainer_id,
            recipient="commander",
            payload=product,
        )
        
        self.to_commander.put(msg)
        self.history.append(msg)
        self.stats["agents_delivered"] += 1
        
        logger.info(f"[BRIDGE] Delivered → Commander: {product.get('agent_id')}")
        return msg.msg_id
    
    def send_stats(self, trainer_pool_stats: Dict) -> str:
        """أرسل إحصاءات للقائد"""
        msg = BridgeMessage(
            msg_type=BridgeMessageType.TRAINING_STATS,
            sender="training_factory",
            recipient="commander",
            payload=trainer_pool_stats,
        )
        
        self.to_commander.put(msg)
        self.history.append(msg)
        return msg.msg_id
    
    def quality_alert(self, trainer_id: str, issue: str) -> str:
        """تنبيه جودة للقائد"""
        msg = BridgeMessage(
            msg_type=BridgeMessageType.QUALITY_ALERT,
            sender=trainer_id,
            recipient="commander",
            payload={"issue": issue, "trainer": trainer_id},
        )
        
        self.to_commander.put(msg)
        self.history.append(msg)
        return msg.msg_id
    
    # ─── استقبال ───
    
    def receive_order(self, timeout: float = 0.1) -> Optional[BridgeMessage]:
        """التدريب يستقبل طلباً"""
        try:
            return self.to_training.get(timeout=timeout)
        except Exception:
            return None
    
    def receive_delivery(self, timeout: float = 0.1) -> Optional[BridgeMessage]:
        """القائد يستقبل تسليماً"""
        try:
            return self.to_commander.get(timeout=timeout)
        except Exception:
            return None
    
    def status(self) -> Dict:
        return {
            **self.stats,
            "pending_to_training": self.to_training.qsize(),
            "pending_to_commander": self.to_commander.qsize(),
            "pending_requests": len(self.pending_requests),
        }
