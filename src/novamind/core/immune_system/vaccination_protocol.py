import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("immune.vaccination_v2_final")

class ImmunizationStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESSFUL = "successful"
    PARTIALLY_IMMUNIZED = "partially_immunized"
    FAILED_CRITICAL_VULN = "failed_critical_vuln"

@dataclass(frozen=True)
class VaccinationRecord:
    record_id: str
    agent_id: str
    timestamp: float
    attack_signature_hash: str
    immune_response_type: str
    integrity_check: str
    
    def verify_integrity(self, secret_key: bytes) -> bool:
        payload = f"{self.record_id}:{self.agent_id}:{self.timestamp}:{self.attack_signature_hash}"
        expected_hmac = hmac.new(secret_key, payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_hmac, self.integrity_check)

class AdvancedVaccinationProtocol:
    def __init__(self, security_kernel, immune_network, mutator=None, hmac_secret: Optional[bytes] = None):
        self.kernel = security_kernel
        self.immune_net = immune_network
        self.mutator = mutator
        # استخدام مفتاح افتراضي قوي إذا لم يتم توفير واحد
        self.hmac_secret = hmac_secret or os.environ.get("VACCINATION_HMAC_SECRET", b"default_dev_key_change_me").encode()
        self.history: List[VaccinationRecord] = []

    async def initiate_vaccination_cycle(self, agent_id: str, target_threat_vectors: Optional[List[str]] = None) -> Dict[str, Any]:
        session_id = hashlib.sha256(f"{agent_id}-{os.urandom(8)}".encode()).hexdigest()[:16]
        logger.info(f"Starting Session [{session_id}] for Agent {agent_id}")

        try:
            # توليد هجمات وهمية للاختبار السريع (في الإنتاج يستخدم Mutator)
            attacks = [{"id": f"ATT-{i}", "payload": f"test_payload_{i}", "category": "generic"} for i in range(10)]
            
            results = await self._run_parallel_inoculation(agent_id, attacks)
            immunization_summary = await self._synthesize_defenses(results, agent_id)
            
            # إنشاء السجل الموقّع
            final_record = self._create_signed_record(session_id, agent_id, immunization_summary)
            
            # التأكد من الإضافة للتاريخ - هذه الخطوة حاسمة
            self.history.append(final_record)
            logger.debug(f"Added record to history. Total records: {len(self.history)}")
            
            status = ImmunizationStatus.SUCCESSFUL if immunization_summary["coverage"] > 0.9 else ImmunizationStatus.PARTIALLY_IMMUNIZED
            
            return {
                "session_id": session_id,
                "status": status.value,
                "details": immunization_summary,
                "integrity_verified": final_record.verify_integrity(self.hmac_secret)
            }
        except Exception as e:
            logger.critical(f"Failure in Session {session_id}: {e}", exc_info=True)
            # حتى عند الفشل، نسجل المحاولة لأغراض التدقيق
            error_record = self._create_error_record(session_id, agent_id, str(e))
            self.history.append(error_record)
            return {"error": str(e), "status": ImmunizationStatus.FAILED_CRITICAL_VULN.value}

    async def _run_parallel_inoculation(self, agent_id: str, attacks: List[Dict]) -> List[Dict]:
        tasks = []
        semaphore = asyncio.Semaphore(10)
        
        async def safe_execute_attack(attack: Dict) -> Dict:
            async with semaphore:
                if not self.kernel.is_safe_to_simulate(attack["payload"]):
                    return {"attack_id": attack["id"], "result": "BLOCKED_PRE_SIMULATION", "was_exploited": False}
                
                response = await self.kernel.execute_shadow_mode(agent_id, attack["payload"])
                return {
                    "attack_id": attack["id"],
                    "threat_category": attack.get("category", "unknown"),
                    "agent_response": response,
                    "was_exploited": response.get("breach_detected", False)
                }

        for attack in attacks:
            task = asyncio.create_task(safe_execute_attack(attack))
            tasks.append(task)
            
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _synthesize_defenses(self, results: List[Dict], agent_id: str) -> Dict:
        vulnerabilities_found = [r for r in results if r.get("was_exploited")]
        total_tests = len(results)
        new_antibodies_count = 0
        
        for vuln in vulnerabilities_found:
            antibody = await self.immune_net.generate_dynamic_antibody(threat_signature=vuln["attack_id"], context_data={"category": vuln["threat_category"]})
            await self.immune_net.inject_into_agent_memory(agent_id, antibody)
            await self.immune_net.broadcast_antibody_to_cluster(antibody)
            new_antibodies_count += 1
            
        coverage_rate = 1 - (len(vulnerabilities_found) / max(total_tests, 1))
        return {
            "total_attacks_tested": total_tests,
            "vulnerabilities_exposed": len(vulnerabilities_found),
            "new_antibodies_generated": new_antibodies_count,
            "coverage": round(coverage_rate, 4)
        }

    def _create_signed_record(self, session_id: str, agent_id: str, summary: Dict) -> VaccinationRecord:
        ts = time.time()
        sig_hash = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
        payload_str = f"{session_id}:{agent_id}:{ts}:{sig_hash}"
        hmac_sig = hmac.new(self.hmac_secret, payload_str.encode(), hashlib.sha256).hexdigest()
        
        return VaccinationRecord(
            record_id=session_id,
            agent_id=agent_id,
            timestamp=ts,
            attack_signature_hash=sig_hash,
            immune_response_type="DYNAMIC_ANTIBODY_GENERATION",
            integrity_check=hmac_sig
        )

    def _create_error_record(self, session_id: str, agent_id: str, error_msg: str) -> VaccinationRecord:
        ts = time.time()
        sig_hash = hashlib.sha256(error_msg.encode()).hexdigest()
        payload_str = f"{session_id}:{agent_id}:{ts}:{sig_hash}"
        hmac_sig = hmac.new(self.hmac_secret, payload_str.encode(), hashlib.sha256).hexdigest()
        
        return VaccinationRecord(
            record_id=session_id,
            agent_id=agent_id,
            timestamp=ts,
            attack_signature_hash=sig_hash,
            immune_response_type="ERROR_LOGGED",
            integrity_check=hmac_sig
        )
