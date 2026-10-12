import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Any

logger = logging.getLogger("immune.twin_scheduler")

class SchedulerState(Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    TRAINING_ACTIVE = "training_active"
    COOLDOWN = "cooldown"

@dataclass
class TwinSessionConfig:
    min_idle_load_threshold: float = 0.3
    max_training_duration_sec: int = 600
    training_interval_hours: float = 4.0
    cooldown_period_min: int = 5
    enable_auto_broadcast: bool = True

class AdversarialTwinScheduler:
    def __init__(self, vaccination_protocol, load_monitor, security_kernel, immune_network, config: TwinSessionConfig = None):
        self.protocol = vaccination_protocol
        self.monitor = load_monitor
        self.kernel = security_kernel
        self.network = immune_network
        self.config = config or TwinSessionConfig()
        self.state: SchedulerState = SchedulerState.IDLE
        self.last_training_time: float = 0.0
        self.next_training_due: float = time.time() + 60
        self._daemon_task: Optional[asyncio.Task] = None
        self._current_session_id: Optional[str] = None

    async def start_daemon(self):
        if self._daemon_task and not self._daemon_task.done():
            return
        self._daemon_task = asyncio.create_task(self._main_loop())

    async def stop_daemon(self):
        if self._daemon_task:
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass

    async def _main_loop(self):
        while True:
            try:
                await self._evaluate_state_transition()
                await asyncio.sleep(30) 
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Main Loop: {e}")
                await asyncio.sleep(60)

    async def _evaluate_state_transition(self):
        current_time = time.time()
        system_load = await self.monitor.get_current_load()
        hours_since_last = (current_time - self.last_training_time) / 3600.0
        
        should_trigger_training = (hours_since_last >= self.config.training_interval_hours and system_load <= self.config.min_idle_load_threshold)

        if should_trigger_training:
            await self._execute_training_cycle()
            return

        if self.state == SchedulerState.COOLDOWN:
            if current_time > self.next_training_due:
                self.state = SchedulerState.MONITORING
            return

        if self.state != SchedulerState.TRAINING_ACTIVE:
            self.state = SchedulerState.MONITORING

    async def _execute_training_cycle(self):
        session_id = f"TWIN-{int(time.time())}"
        self._current_session_id = session_id
        self.state = SchedulerState.TRAINING_ACTIVE
        start_ts = time.time()

        try:
            target_agent_id = "Agent_Primary_ShadowClone" 
            result = await asyncio.wait_for(
                self.protocol.initiate_vaccination_cycle(agent_id=target_agent_id),
                timeout=self.config.max_training_duration_sec
            )
            
            duration = time.time() - start_ts
            logger.info(f"Session {session_id} completed in {duration:.2f}s")
            
            if result.get("status") == "successful":
                self.last_training_time = time.time()
            elif result.get("status") == "failed_critical_vuln":
                logger.critical(f"CRITICAL VULN DETECTED: {result.get('error')}")
                self.last_training_time = time.time()
            else:
                self.last_training_time = time.time() 

        except asyncio.TimeoutError:
            logger.error(f"Session {session_id} TIMED OUT")
            self.last_training_time = time.time()
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
        finally:
            self.state = SchedulerState.COOLDOWN
            self.next_training_due = time.time() + (self.config.cooldown_period_min * 60)
            self._current_session_id = None

    def get_status_report(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "last_training_timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_training_time)),
            "next_expected_training": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_training_time + self.config.training_interval_hours * 3600)),
            "active_session": self._current_session_id
        }
