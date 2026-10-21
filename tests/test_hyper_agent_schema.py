"""BUG-5 regression: hyper_agent uses a strict JSON schema."""
from hyper_agent import HYPER_AGENT_SCHEMA


def test_schema_has_exactly_4_actions():
    """Only CODE/TEST/DONE/ERROR are valid — no free text."""
    actions = HYPER_AGENT_SCHEMA["properties"]["action"]["enum"]
    assert sorted(actions) == ["CODE", "DONE", "ERROR", "TEST"]


def test_schema_requires_action_and_content():
    """Both fields must be present — no partial plans."""
    assert sorted(HYPER_AGENT_SCHEMA["required"]) == ["action", "content"]


def test_schema_forbids_extra_fields():
    """No additionalProperties — model cannot invent fields."""
    assert HYPER_AGENT_SCHEMA.get("additionalProperties") is False


def test_parse_action_accepts_schema_output():
    """_parse_action must accept exactly what generate_json returns."""
    from hyper_agent import _parse_action
    import json
    raw = json.dumps({"action": "CODE", "content": "print(1)"})
    result = _parse_action(raw)
    assert result["action"] == "CODE"
    assert result["content"] == "print(1)"
