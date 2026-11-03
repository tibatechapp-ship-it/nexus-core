"""Independent quality gate (90-day plan, M3.1) — separate process, own log.

بوابة مستقلة عمليةً عن المحرك: اختبارات ثم أمن ثم سلامة، وقرار واحد
يُكتب في سجل JSONL كامل الحقول قبل رؤيته.
"""

from __future__ import annotations

from src.quality_gate.runner import default_gates, run_gate

__all__ = ["default_gates", "run_gate"]
