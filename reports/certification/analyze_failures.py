#!/usr/bin/env python3
"""Analyze failures and categorize them for handling."""
import json
from pathlib import Path
from collections import Counter

ROOT = Path('/data/data/com.termux/files/home/nexus-core')
RESULTS = ROOT / 'reports' / 'certification' / 'smoke_results_v3.json'

data = json.loads(RESULTS.read_text())

# صنّف حسب الحالة
by_status = {}
for r in data:
    s = r.get('smoke_status', '?')
    by_status.setdefault(s, []).append(r)

print("=" * 70)
print("📊 تصنيف النتائج")
print("=" * 70)

for status, agents in sorted(by_status.items()):
    print(f"\n{status}: {len(agents)}")
    for a in agents[:20]:
        err = a.get('smoke_error', '')
        method = a.get('method_used', '')
        extra = f" [{method}]" if method else ""
        extra += f" — {err[:80]}" if err else ""
        print(f"  • {a['name']}{extra}")
    if len(agents) > 20:
        print(f"  ... و {len(agents) - 20} آخرين")

# تصنيف الفاشلين حسب السبب
print()
print("=" * 70)
print("🎯 استراتيجية المعالجة")
print("=" * 70)

strategies = {
    'NO_CLASS': '❌ استثناء (ليس وكيلاً)',
    'NO_RUN_METHOD': '🔧 إضافة طريقة (analyze/execute)',
    'INIT_FAILED': '🔧 إصلاح __init__',
    'CALL_FAILED': '🔧 فحص كود الوكيل',
    'EMPTY': '🔧 فحص prompt',
    'ERROR': '🔧 إصلاح imports',
    'TIMEOUT': '🔧 زيادة timeout',
}

for status, action in strategies.items():
    if status in by_status:
        print(f"  {status} ({len(by_status[status])}): {action}")

# حفظ النتائج
summary = {s: len(a) for s, a in by_status.items()}
(ROOT / 'reports' / 'certification' / 'failure_summary.json').write_text(
    json.dumps(summary, indent=2, ensure_ascii=False)
)
print()
print("✅ تم الحفظ في failure_summary.json")
