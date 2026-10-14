"""Tests for the council recommendation extractor (v1.9.2)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from src.council.recommend import extract_recommendation


def _entry(member, text):
    return {"phase": "independent", "member": member, "response": text}


def test_majority_recommendation_wins():
    transcript = [
        _entry("profiler", "رأيي... [التوصية: pytest]"),
        _entry("analyst", "أتفق... [التوصية: pytest]"),
        _entry("critic", "لكن... [التوصية: unittest]"),
    ]
    assert extract_recommendation(transcript) == "pytest"


def test_ignores_agent_word_as_recommendation():
    transcript = [
        _entry("profiler", "[التوصية: analyst]"),
        _entry("analyst", "[التوصية: pytest]"),
    ]
    assert extract_recommendation(transcript) == "pytest"


def test_ignores_dirty_prompt_fragments():
    transcript = [
        _entry("profiler", "[التوصية: خلاصة جوابك في 5 كلمات]"),
        _entry("analyst", "[التوصية: pytest]"),
    ]
    assert extract_recommendation(transcript) == "pytest"


def test_strips_angle_brackets_and_dots():
    transcript = [_entry("profiler", "[التوصية: <pytest>.]")]
    assert extract_recommendation(transcript) == "pytest"


def test_empty_when_no_markers():
    assert extract_recommendation([_entry("profiler", "لا توصية هنا")]) == ""
    assert extract_recommendation([]) == ""
    assert extract_recommendation(None) == ""


def test_handles_non_dict_entries():
    """مدخلات نصية خام لا تُسقط الدالة."""
    assert extract_recommendation(["نص خام [التوصية: redis]"]) == "redis"


def test_cache_hit_transcript_yields_recommendation():
    """السيناريو الفعلي للبند ②: transcript من الكاش يعطي توصية كاملة."""
    cached_transcript = [
        _entry("profiler", "[الحكم: موافق]\n[التوصية: pytest]"),
        _entry("analyst", "[الحكم: موافق]\n[التوصية: pytest]"),
        _entry("critic", "[الحكم: موافق]\n[التوصية: unittest]"),
    ]
    assert extract_recommendation(cached_transcript) == "pytest"
