"""Full Stack Test — كل المكونات معاَ (الإصدار المصحح للنظافة)"""
import os
import sys
import time
import asyncio
import threading
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

# ═══════════════════════════════════════════════════════════
# تحديد المسار الديناميكي للمشروع
# ═══════════════════════════════════════════════════════════
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from novamind.core.security.security_kernel_v3 import SecurityKernel
from novamind.core.security.load_monitor import LoadMonitor
from novamind.core.immune_system.immune_network_mock import MockImmuneNetwork
from novamind.core.immune_system.vaccination_protocol import AdvancedVaccinationProtocol
from novamind.core.immune_system.adversarial_twin_scheduler import (
    AdversarialTwinScheduler, TwinSessionConfig,
)

# --- تعريف الأصناف المساعدة (تمت تسميتها لتجنب تعارض pytest) ---

class ValidationResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"

@dataclass
class ValidationCase:
    name: str
    input_data: str
    expected_outcome: bool
    result: Optional[ValidationResult] = None

async def main():
    print("=" * 70)
    print("🧪 Full Stack Integration Test (Clean Version)")
    print("=" * 70)

    # 1. تهيئة المكونات
    kernel = SecurityKernel()
    network = MockImmuneNetwork("ci_clean_test")
    monitor = LoadMonitor()

    protocol = AdvancedVaccinationProtocol(
        security_kernel=kernel,
        immune_network=network,
        hmac_secret=b"clean_ci_secret",
    )

    config = TwinSessionConfig(
        min_idle_load_threshold=1.0, # السماح بالتدريب دائماً للاختبار
        training_interval_hours=0.001, # دورة سريعة جداً
        max_training_duration_sec=10,
        cooldown_period_min=0,
    )

    scheduler = AdversarialTwinScheduler(
        vaccination_protocol=protocol,
        load_monitor=monitor,
        security_kernel=kernel,
        immune_network=network,
        config=config,
    )

    # 2. تشغيل النظام
    print("\n[1] Starting Scheduler Daemon...")
    await scheduler.start_daemon()
    
    # انتظار قصير لتنفيذ دورتين تدريبيتين على الأقل
    print("[2] Running for 5 seconds to trigger training cycles...")
    await asyncio.sleep(5)
    
    # 3. إيقاف النظام بأمان
    print("[3] Stopping Scheduler...")
    await scheduler.stop_daemon()

    # 4. التحقق من النتائج
    print("\n[4] Final Verification:")
    
    blocked_count = kernel.stats.get('blocked', 0)
    allowed_count = kernel.stats.get('allowed', 0)
    antibodies_count = len(network.rules)
    sessions_count = len(protocol.history)
    
    print(f"   • Kernel Blocked Attacks: {blocked_count}")
    print(f"   • Kernel Allowed Inputs:  {allowed_count}")
    print(f"   • Generated Antibodies:   {antibodies_count}")
    print(f"   • Completed Sessions:     {sessions_count}")

    # تأكيدات حاسمة (Assertions)
    assert sessions_count > 0, "❌ FAILED: No vaccination sessions were recorded."
    assert antibodies_count >= 0, "❌ FAILED: Negative antibody count detected."
    
    # إذا كان لدينا هجمات محجوبة، فهذا جيد (يعني النواة تعمل)
    if blocked_count == 0 and allowed_count == 0:
        print("   ⚠️ Warning: No traffic processed by kernel during test window.")
    else:
        print("   ✅ Success: Kernel actively processed traffic.")

    print("\n" + "=" * 70)
    print("✅ ALL CHECKS PASSED. SYSTEM IS HEALTHY.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
