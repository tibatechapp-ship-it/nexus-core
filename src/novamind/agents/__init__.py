
# ─── Maintenance Agent (self-healing) ───
try:
    from novamind.agents.maintenance_agent import maintenance_agent
except ImportError:
    maintenance_agent = None
