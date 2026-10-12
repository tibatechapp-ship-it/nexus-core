import asyncio
try:
    import psutil
except ImportError:
    psutil = None

class LoadMonitor:
    async def get_current_load(self) -> float:
        if psutil:
            loop = asyncio.get_event_loop()
            cpu = await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=0.1) / 100.0)
            return cpu
        return 0.5

    async def get_recent_anomalies(self, window_minutes: int = 5) -> list:
        return []
