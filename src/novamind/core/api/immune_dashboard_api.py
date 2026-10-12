from fastapi import FastAPI
from datetime import datetime
import sys
import os

# إضافة المسار للمشروع
sys.path.insert(0, "/public/agent/novamind")

from novamind.core.security.security_kernel_v3 import SecurityKernel
from novamind.core.security.load_monitor import LoadMonitor
from novamind.core.immune_system.immune_network_mock import MockImmuneNetwork
from novamind.core.immune_system.vaccination_protocol import AdvancedVaccinationProtocol
from novamind.core.immune_system.adversarial_twin_scheduler import AdversarialTwinScheduler, TwinSessionConfig

app = FastAPI(title="NovaMind Immune Dashboard", version="1.0.1")

# Global State - Initialize properly
_state = {
    "scheduler": None, 
    "protocol": None, 
    "monitor": None, 
    "started_at": datetime.now().isoformat()
}

@app.on_event("startup")
async def startup_event():
    kernel = SecurityKernel()
    monitor = LoadMonitor() # Ensure this is instantiated
    network = MockImmuneNetwork("api_cluster")
    
    # Use a fixed secret for consistency in dev/test
    protocol = AdvancedVaccinationProtocol(kernel, network, hmac_secret=b"api_fixed_secret")
    
    config = TwinSessionConfig(training_interval_hours=100) # Disable auto-training for stability
    scheduler = AdversarialTwinScheduler(protocol, monitor, kernel, network, config=config)
    
    _state["scheduler"] = scheduler
    _state["protocol"] = protocol
    _state["monitor"] = monitor
    
    await scheduler.start_daemon()

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "novamind-immune-api", "started_at": _state["started_at"]}

@app.get("/status")
async def get_status():
    sched = _state["scheduler"]
    if not sched:
        return {"error": "Scheduler not initialized"}
    return sched.get_status_report()

@app.get("/metrics")
async def get_metrics():
    proto = _state["protocol"]
    mon = _state["monitor"]
    
    # Safety check for monitor
    if mon is None:
        load_val = 0.0
    else:
        load_val = await mon.get_current_load()
        
    hist_len = len(proto.history) if proto else 0
    antibodies_count = len(proto.immune_net.rules) if proto and hasattr(proto.immune_net, 'rules') else 0
    
    return {
        "system_load": round(load_val, 2),
        "total_vaccinations": hist_len,
        "active_antibodies": antibodies_count,
        "timestamp": datetime.now().isoformat()
    }
