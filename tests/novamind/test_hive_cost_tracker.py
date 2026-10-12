"""اختبارات Cost Tracker — متوافقة مع Schema الموجود."""
import sys
from pathlib import Path

# [FIXED PATH] Use relative imports or conftest.py instead

from novamind.core.hive.analytics import cost_tracker as ct


def setup_function(_):
    """ينظّف DB قبل كل اختبار."""
    ct.reset()


def test_record_cost_success():
    ct.record_cost(provider="groq-01", tokens=1000, duration_ms=500)
    total = ct.get_total_cost()
    assert total["calls"] == 1
    assert total["tokens"] == 1000
    assert total["failures"] == 0


def test_record_cost_free_provider():
    """groq مجاني، فالتكلفة صفر."""
    ct.record_cost(provider="groq-01", tokens=5000)
    total = ct.get_total_cost()
    assert total["cost_usd"] == 0.0


def test_record_cost_paid_provider():
    """glm بتكلفة 0.001 لكل 1K."""
    ct.record_cost(provider="glm-01", tokens=2000)
    total = ct.get_total_cost()
    assert total["cost_usd"] > 0
    assert abs(total["cost_usd"] - 0.002) < 0.0001


def test_record_cost_failure():
    ct.record_cost(
        provider="glm-01",
        tokens=0,
        success=False,
        error="429 Too Many Requests",
    )
    total = ct.get_total_cost()
    assert total["failures"] == 1


def test_provider_stats():
    ct.record_cost(provider="groq-01", tokens=1000)
    ct.record_cost(provider="groq-01", tokens=2000)
    ct.record_cost(provider="glm-01", tokens=500)
    stats = ct.get_provider_stats()
    assert len(stats) == 2
    groq = next(s for s in stats if s["provider"] == "groq-01")
    assert groq["calls"] == 2
    assert groq["tokens"] == 3000


def test_daily_cost():
    ct.record_cost(provider="groq-01", tokens=1000)
    daily = ct.get_daily_cost()
    assert daily["calls"] == 1
    assert daily["tokens"] == 1000


def test_agent_id_recorded():
    ct.record_cost(provider="groq-01", tokens=100, agent_id="coder")
    import sqlite3
    con = sqlite3.connect(str(ct.DB_PATH))
    row = con.execute("SELECT agent_id FROM costs ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    assert row[0] == "coder"


def test_non_blocking_on_bad_input():
    """لا يرفع استثناءات أبداً."""
    ct.record_cost(provider="", tokens=-100)
    ct.record_cost(provider="x", tokens="bad")  # type: ignore
    assert True
