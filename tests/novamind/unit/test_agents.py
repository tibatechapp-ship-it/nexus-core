"""Test the core agents with sample code."""
import pytest


def test_security_agent_detects_eval():
    """SecurityAgent should detect eval()."""
    from novamind.agents.security_agent import security_agent
    code = 'eval("2+2")'
    result = security_agent.analyze(code, "test.py")
    assert result["total"] > 0
    assert any("eval" in i["description"].lower() for i in result["issues"])


def test_security_agent_detects_hardcoded():
    """SecurityAgent should detect hardcoded secrets."""
    from novamind.agents.security_agent import security_agent
    code = 'password = "hardcoded123"'
    result = security_agent.analyze(code, "test.py")
    assert result["total"] > 0


def test_performance_agent_detects_nested_loops():
    """PerformanceAgent should detect nested loops via AST."""
    from novamind.agents.performance_agent import performance_agent
    code = """def foo():
    for i in range(10):
        for j in range(10):
            pass
"""
    result = performance_agent.analyze(code, "test.py")
    # Nested loop detection uses AST
    assert result["total"] > 0


def test_performance_agent_detects_magic():
    """PerformanceAgent should detect magic number in loop."""
    from novamind.agents.performance_agent import performance_agent
    code = 'for i in range(len(items)):\n    pass'
    result = performance_agent.analyze(code, "test.py")
    assert result["total"] > 0


def test_documentation_agent_detects_missing():
    """DocumentationAgent should detect missing docstrings."""
    from novamind.agents.documentation_agent import documentation_agent
    code = "def foo():\n    return 42"
    result = documentation_agent.analyze(code, "test.py")
    assert result["total"] > 0


def test_refactor_agent_detects_magic_numbers():
    """RefactorAgent should detect magic numbers."""
    from novamind.agents.refactor_agent import refactor_agent
    code = "x = 500\ny = x + 999"
    result = refactor_agent.analyze(code, "test.py")
    assert result["total"] > 0


def test_migration_agent_detects_py2():
    """MigrationAgent should detect Python 2 code."""
    from novamind.agents.migration_agent import migration_agent
    code = 'print "hello"'
    result = migration_agent.analyze(code, "test.py")
    assert result["total"] > 0


def test_code_review_agent_reviews():
    """CodeReviewAgent should produce a review."""
    from novamind.agents.code_review_agent import code_review_agent
    code = 'eval("x")\npassword = "123"'
    result = code_review_agent.review(code, "test.py",
                                        dimensions=["security"])
    assert result["total_issues"] > 0
    assert 0 <= result["score"] <= 100
