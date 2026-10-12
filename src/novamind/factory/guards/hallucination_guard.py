"""Hallucination Guard — يكتشف الكذب في مخرجات LLM."""
from __future__ import annotations
from typing import Dict, Any, List
import re

from novamind.factory.guards.base import GuardResult


class HallucinationGuard:
    """يكشف مظاهر الهلوسة في ردود LLM."""
    name = "hallucination_guard"

    SUSPICIOUS_PHRASES = [
        "as of my last update",
        "i don't have access",
        "i cannot browse",
        "according to my training",
        "i'm not sure but",
        "i believe that",
        "probably works",
        "should work but",
        "as far as i know",
        "i may be wrong",
    ]

    def __init__(self, strict: bool = False):
        self.strict = strict

    def check(self, data: Dict[str, Any]) -> GuardResult:
        result = GuardResult(passed=True, guard_name=self.name)

        text = data.get("text") or data.get("raw") or ""
        code = data.get("code") or ""

        if not text and not code:
            return result

        combined = f"{text}\n{code}"

        # 1. phrases مشبوهة
        found = []
        for phrase in self.SUSPICIOUS_PHRASES:
            if phrase.lower() in combined.lower():
                found.append(phrase)
        if found:
            result.add_warning(f"phrases مشبوهة: {found[:3]}")

        # 2. يدّعي إنشاء ملف بدون path
        low = combined.lower()
        if ("wrote" in low or "created" in low or "saved" in low):
            if "/public/" not in combined and "/tmp/" not in combined:
                # قد يكون ملف نسبي عادي — تحذير فقط
                pass

        # 3. يدّعي تشغيل اختبار بدون نتيجة
        if "pytest" in low and "passed" not in low and "failed" not in low:
            result.add_warning("ذُكر pytest بدون نتيجة واضحة")

        # 4. strict mode
        if self.strict and result.warnings:
            result.passed = False

        return result


def add_hallucination_to_chain():
    from novamind.factory.guards.chain import build_default_chain
    chain = build_default_chain()
    chain.add(HallucinationGuard())
    return chain
