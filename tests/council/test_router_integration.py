"""Tests for router integration."""
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.council.router_integration import (
    should_use_council, get_council_reason
)


@pytest.mark.parametrize("question,expected", [
    ("هل نستخدم FastAPI أم Flask؟", True),
    ("كيف أكتب دالة Python؟", False),
    ("أيهما أفضل: SQLite أم PostgreSQL؟", True),
    ("راجع هذا الكود", False),
    ("هل ننشر في production؟", True),
    ("افحص أمنياً", True),
    ("ما هو الطقس؟", False),
    ("هناك ثغرة أمنية", True),
    ("اكتب دالة جمع", False),
    ("أمنية عالية", True),
    ("قارن بين FastAPI و Flask", True),
    ("ما الفرق بين SQLite و PostgreSQL", True),
    ("مقارنة شاملة", True),
])
def test_should_use_council(question, expected):
    assert should_use_council(question) == expected


def test_reason_high_risk():
    assert get_council_reason("هل ننشر في production؟") == "risk-high"


def test_reason_decision_signal():
    assert get_council_reason("هل نستخدم FastAPI أم Flask؟") == "decision-signal"


def test_reason_no_council():
    assert get_council_reason("كيف حالك؟") == "no-council"
