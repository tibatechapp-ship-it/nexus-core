#!/usr/bin/env python3
"""Standalone script for cron-based daily reporting."""
import sys
import asyncio
import logging

# Add project root to path
# [FIXED PATH] Use relative imports or conftest.py instead

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("DailyJob")

async def main():
    try:
        from hive.agents import get_tool_agent # Ensures agents loaded
        from hive.agents.orchestrator import get_orchestrator
        from hive.agents.report_generator import get_report_generator
        
        orch = get_orchestrator()
        reporter = get_report_generator(orch)
        
        log.info("Running scheduled report generation...")
        await reporter.run_scheduled_report()
        log.info("Scheduled report finished.")
        
    except Exception as e:
        log.exception("Fatal error in daily report job")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
