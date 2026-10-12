"""
ExtendedCommander — القائد الذي يطلب وكلاء جدد
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import time
import random
import logging

logger = logging.getLogger("commander_ext")


class ExtendedCommander:
    """القائد الأعلى الموسّع — يراقب ويطلب وكلاء جدد"""

    def __init__(self, bridge, realm_manager):
        self.name = "supreme_commander"
        self.bridge = bridge
        self.realm_manager = realm_manager
        self.requested_agents: List[Dict] = []
        self.received_agents: List[Dict] = []
        self.system_state = {"operations": {}, "gaps": []}
        self.auto_request_enabled = True
        self.gap_threshold = 3
        logger.info("ExtendedCommander ready")

    def analyze_gaps(self) -> List[Dict]:
        """تحليل النقص في النظام"""
        gaps = []
        domains = ["coding", "security", "devops", "quality", "database"]
        for domain in domains:
            deficit = self._compute_domain_deficit(domain)
            if deficit > self.gap_threshold:
                gaps.append({
                    "domain": domain,
                    "deficit": deficit,
                    "urgency": self._compute_urgency(deficit),
                })
        self.system_state["gaps"] = gaps
        return gaps

    def _compute_domain_deficit(self, domain: str) -> int:
        return random.randint(0, 5)

    def _compute_urgency(self, deficit: int) -> int:
        if deficit >= 5: return 5
        if deficit >= 4: return 4
        if deficit >= 3: return 3
        if deficit >= 2: return 2
        return 1

    def request_new_agent(self, domain: str, spec: str, urgency: int) -> Optional[str]:
        """اطلب وكيلاً جديداً من التدريب"""
        if not self.auto_request_enabled:
            return None
        payload = {
            "spec": spec,
            "domain": domain,
            "urgency": urgency,
            "required_skills": self._infer_required_skills(spec, domain),
            "requested_by": self.name,
        }
        if urgency >= 4:
            msg_id = self.bridge.urgent_order(self.name, payload)
        else:
            msg_id = self.bridge.request_agent(self.name, payload)
        self.requested_agents.append({
            "msg_id": msg_id,
            "payload": payload,
            "at": time.time(),
        })
        logger.info(f"Commander requested {spec} for {domain} (urgency={urgency})")
        return msg_id

    def _infer_required_skills(self, spec: str, domain: str) -> List[str]:
        skill_map = {
            "coder": ["write_function", "write_class", "refactor"],
            "analyzer": ["detect_bugs", "assess_quality"],
            "fixer": ["fix_syntax", "fix_logic"],
            "tester": ["run_tests", "generate_test_cases"],
            "security": ["detect_vulnerabilities", "audit_secrets"],
            "devops": ["build_docker", "deploy_k8s"],
            "quality": ["review_code", "measure_metrics"],
            "learner": ["extract_lessons", "update_knowledge"],
        }
        return skill_map.get(spec, ["basic"])

    def receive_delivery(self, timeout: float = 1.0) -> Optional[Dict]:
        """استلم وكيلاً جاهزاً من التدريب"""
        msg = self.bridge.receive_delivery(timeout=timeout)
        if not msg:
            return None
        if msg.msg_type.value == "agent_delivered":
            agent = msg.payload
            self.received_agents.append(agent)
            logger.info(f"Commander received agent: {agent.get('agent_id')}")
            self._assign_to_deputy(agent)
            return agent
        elif msg.msg_type.value == "training_stats":
            logger.info(f"Training stats received: {msg.payload}")
            return msg.payload
        elif msg.msg_type.value == "quality_alert":
            logger.warning(f"Quality alert: {msg.payload}")
            return msg.payload
        return None

    def _assign_to_deputy(self, agent: Dict):
        logger.info(f"  → Assigned to deputy (domain={agent.get('blueprint', {}).get('domain')})")

    def auto_manage(self):
        """الإدارة التلقائية"""
        gaps = self.analyze_gaps()
        for gap in gaps:
            if gap["urgency"] >= 3:
                self.request_new_agent(
                    domain=gap["domain"],
                    spec=self._infer_spec_from_domain(gap["domain"]),
                    urgency=gap["urgency"],
                )
        while True:
            delivery = self.receive_delivery(timeout=0.1)
            if not delivery:
                break
        logger.info(f"Auto-manage cycle complete (gaps={len(gaps)})")

    def _infer_spec_from_domain(self, domain: str) -> str:
        mapping = {
            "coding": "coder",
            "security": "security",
            "devops": "devops",
            "quality": "quality",
            "database": "coder",
        }
        return mapping.get(domain, "coder")

    def status(self) -> Dict:
        return {
            "commander": self.name,
            "requested": len(self.requested_agents),
            "received": len(self.received_agents),
            "gaps_detected": len(self.system_state["gaps"]),
            "auto_manage": self.auto_request_enabled,
        }
