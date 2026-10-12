#!/usr/bin/env python3
"""Extract sections from novamind.py into separate modules."""
import re
from pathlib import Path

SRC = Path("/public/novamind.py")
lines = SRC.read_text().splitlines(keepends=True)

SECTIONS = {
    "ollama":    (26,   75,  "hive/providers/ollama.py",       "OllamaProvider"),
    "glm":       (76,   197, "hive/providers/glm.py",          "GLMProvider"),
    "groq":      (198,  274, "hive/providers/groq.py",         "GroqProvider"),
    "openrouter":(275,  345, "hive/providers/openrouter.py",   "OpenRouterProvider"),
    "llm_router":(346,  483, "hive/routing/llm_router.py",     "LLMRouter"),
    "moe":       (791,  864, "hive/routing/moe.py",            "SemanticMoERouter"),
    "planner":   (918,  1009,"hive/orchestration/planner.py",  "MultiStepPlanner"),
    "cost":      (3419, 3569,"hive/analytics/cost_tracker_ext.py", "CostTracker"),
    "halluc":    (2467, 2538,"hive/security/hallucination.py", "HallucinationDetector"),
    "anti_halluc":(4151,4432,"hive/security/anti_hallucination.py", "AntiHallucination"),
}

for name, (start, end, dest, cls) in SECTIONS.items():
    dest_path = Path("/public") / dest
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    body = "".join(lines[start-1:end])

    header = f'''"""Extracted from novamind.py — section: {name}
Original lines: {start}-{end}
Class: {cls}
"""
# ═══════════════════════════════════════════════════════
#  AUTO-EXTRACTED — do not edit by hand unless verified
# ═══════════════════════════════════════════════════════

'''

    dest_path.write_text(header + body)
    print(f"✓ {dest}  ({end-start+1} lines)")

print("\n✓ Extraction complete.")
