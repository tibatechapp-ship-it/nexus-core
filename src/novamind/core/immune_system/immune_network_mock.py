from typing import Dict, Any

class MockImmuneNetwork:
    def __init__(self, name: str = "MockNetwork"):
        self.name = name
        self.rules: Dict[str, Dict] = {}
        self.agents: set = set()

    def register_agent(self, agent_id: str):
        self.agents.add(agent_id)

    def has_rule(self, rule_id: str) -> bool:
        return rule_id in self.rules

    def get_rules(self) -> Dict:
        return self.rules

    async def inject_external_antibody(self, antibody_id: str, rule: str, signature_hash: str, metadata: dict = None) -> bool:
        if antibody_id in self.rules:
            return True
        self.rules[antibody_id] = {"rule": rule, "signature": signature_hash, "metadata": metadata or {}, "source": "external"}
        return True

    async def generate_dynamic_antibody(self, threat_signature: str, context_data: dict = None):
        class FakeAb:
            def __init__(self, ab_id, sig):
                self.antibody_id = ab_id
                self.threat_signature = sig
                self.confidence = 0.9
        ab_id = f"mock_ab_{len(self.rules)+1}"
        self.rules[ab_id] = {"rule": threat_signature[:50], "signature": threat_signature}
        return FakeAb(ab_id, threat_signature)

    async def inject_into_agent_memory(self, agent_id: str, antibody):
        return True

    async def broadcast_antibody_to_cluster(self, antibody):
        return True
