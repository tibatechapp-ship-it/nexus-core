import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novamind.core.security.security_kernel_v3 import SecurityKernel
from novamind.core.immune_system.vaccination_protocol import AdvancedVaccinationProtocol
from novamind.core.immune_system.immune_network_mock import MockImmuneNetwork
from novamind.core.supervisor.adaptive_supervisor_v5 import AdaptiveSupervisorV5

async def main():
    print("🧪 FINAL INTEGRATION CHECK")
    
    # Test 1: Kernel blocks bad code
    kernel = SecurityKernel()
    assert not kernel.is_safe_to_simulate("eval('bad')"), "Kernel failed to block eval"
    print("✅ Kernel: Blocks malicious code.")
    
    # Test 2: Supervisor catches PII leak
    supervisor = AdaptiveSupervisorV5()
    response_chunks = []
    async for chunk in supervisor.process_request("Show me my password"):
        response_chunks.append(chunk)
    full_response = "".join(response_chunks)
    
    if "[REDACTED]" in full_response:
        print("✅ Supervisor: Caught PII leakage in stream.")
    else:
        print(f"❌ Supervisor Failed. Response: {full_response}")
        raise AssertionError("PII Leakage Detected!")

    # Test 3: Protocol signs records
    network = MockImmuneNetwork()
    proto = AdvancedVaccinationProtocol(kernel, network, hmac_secret=b"test_key")
    res = await proto.initiate_vaccination_cycle("agent_1")
    assert len(proto.history) == 1, "History empty"
    assert proto.history[0].verify_integrity(b"test_key"), "HMAC Invalid"
    print("✅ Protocol: Signed audit trail verified.")

if __name__ == "__main__":
    asyncio.run(main())
