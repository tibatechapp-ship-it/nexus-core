"""اختبارات A2A — conformance كامل (docs/V2_ROADMAP.md م4 — ض3).

بوابة الخروج (حرفيًا): «بطاقة صالحة + دورة اكتشاف/رسالة/رد كاملة»
— بلا أي اعتمادية خارجية ولا شبكة: النقل مُحقَن، والمبادل المرجعي
بطاقة مرجعية مخزنة في ``tests/fixtures/a2a_reference_card.json``.
"""

from __future__ import annotations

import json
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.a2a import (
    A2A_PROTOCOL_VERSION,
    AgentCard,
    A2AClient,
    JsonRpcError,
    PrivacyError,
    a2a_allowlist,
    build_agent_cards,
    build_hub_card,
    card_to_dict,
    handle_jsonrpc,
    handle_message_send,
    host_allowed,
    validate_card,
)

_ROOT = Path(__file__).resolve().parents[1]


def _load_gateway() -> Any:
    """البوابة الموحدة (unified_agent.py) — مسارات A2A تعيش فيها
    بعد حذف اللوحة القديمة (v1.61.0: المسارات نُقلت فنُقل الاختبار معها)."""
    name = "_nexus_gateway_a2a"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, _ROOT / "src" / "legacy_root" / "unified_agent.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


app = _load_gateway().app

FIXTURE_CARD = Path(__file__).resolve().parent / "fixtures" / "a2a_reference_card.json"

# ═══ 1. البطاقة — صرامة المواصفة ═════════════════════════════════════════════════


def test_protocol_version_pinned() -> None:
    assert A2A_PROTOCOL_VERSION == "0.3.0"


def test_hub_card_is_spec_valid() -> None:
    problems = validate_card(build_hub_card().to_dict())
    assert problems == []


def test_reference_fixture_card_is_spec_valid() -> None:
    d = json.loads(FIXTURE_CARD.read_text(encoding="utf-8"))
    assert validate_card(d) == []


def test_card_camel_case_wire_shape() -> None:
    d = build_hub_card().to_dict()
    for key in ("protocolVersion", "defaultInputModes",
                "defaultOutputModes", "capabilities"):
        assert key in d
    assert "protocol_version" not in d and "input_modes" not in d


def test_validate_card_detects_missing_fields() -> None:
    problems = validate_card({"name": "x"})
    assert any("missing field" in p for p in problems)


def test_validate_card_rejects_bad_url_and_version() -> None:
    d = build_hub_card().to_dict()
    d["url"] = "ftp://nope"
    d["protocolVersion"] = "9.9"
    problems = validate_card(d)
    assert any("url" in p for p in problems)
    assert any("protocolVersion" in p for p in problems)


def test_validate_card_requires_skill_fields() -> None:
    d = build_hub_card().to_dict()
    d["skills"] = [{"id": "x"}]
    problems = validate_card(d)
    assert sum(1 for p in problems if "skills[0]" in p) >= 3


# ═══ 2. البطاقات من الجرد — مصدر واحد للحقيقة ════════════════════════════════════


def test_fleet_cards_generated_and_valid() -> None:
    cards = build_agent_cards()
    assert len(cards) >= 100  # الأسطول 106 — لا قائمة موازية
    ds = [c.to_dict() for c in cards]
    assert all(validate_card(d) == [] for d in ds)


def test_fleet_card_names_unique_and_prefixed() -> None:
    cards = build_agent_cards()
    names = [c.name for c in cards]
    assert len(set(names)) == len(names)
    assert all(n.startswith("nexus-") for n in names)


def test_card_version_matches_platform_version() -> None:
    from src import __version__

    assert build_hub_card().version == str(__version__)


def test_card_version_follows_inventory_not_hardcoded() -> None:
    """بطاقة على جرد مُحقن — لا استيراد ولا شبكة (source injectable)."""
    fake = AgentCard(name="f", description="d", url="http://x/api/a2a/message",
                     version="0")
    assert fake.to_dict()["protocolVersion"] == A2A_PROTOCOL_VERSION


# ═══ 3. المُرسِل — JSON-RPC ═══════════════════════════════════════════════════════


def _user_message(text: str) -> dict[str, Any]:
    return {"role": "user", "kind": "message", "messageId": "m-1",
            "parts": [{"type": "text", "text": text}]}


def test_message_send_round_trip() -> None:
    result = handle_message_send({"message": _user_message("مرحبا")})
    assert result["role"] == "agent" and result["kind"] == "message"
    assert result["parts"][0]["type"] == "text"
    assert result["parts"][0]["text"]
    assert result["contextId"] == "m-1"


def test_message_send_custom_handler() -> None:
    result = handle_message_send(
        {"message": _user_message("hi")},
        text_handler=lambda t: f"E:{t}",
    )
    assert result["parts"][0]["text"] == "E:hi"


def test_message_send_invalid_params() -> None:
    with pytest.raises(JsonRpcError) as ei:
        handle_message_send({})
    assert ei.value.code == -32602


def test_jsonrpc_ok_envelope() -> None:
    resp = handle_jsonrpc({"jsonrpc": "2.0", "id": 7,
                           "method": "message/send",
                           "params": {"message": _user_message("x")}})
    assert resp["jsonrpc"] == "2.0" and resp["id"] == 7
    assert "result" in resp and "error" not in resp


def test_jsonrpc_method_not_found() -> None:
    resp = handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "nope"})
    assert resp["error"]["code"] == -32601


def test_jsonrpc_bad_envelope_is_parse_error() -> None:
    resp = handle_jsonrpc({"id": 2})
    assert resp["error"]["code"] == -32700


def test_jsonrpc_handler_crash_is_internal_error_not_leak() -> None:
    def boom(text: str) -> str:
        raise RuntimeError("secret internals")

    resp = handle_jsonrpc({"jsonrpc": "2.0", "id": 3,
                           "method": "message/send",
                           "params": {"message": _user_message("x")}},
                          text_handler=boom)
    assert resp["error"]["code"] == -32603
    assert "secret" not in json.dumps(resp)


# ═══ 4. الخصوصية — الصادر بقائمة سماح صريحة ══════════════════════════════════════


def test_allowlist_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_A2A_ALLOWLIST", "Peer.Example, other.org")
    assert a2a_allowlist() == ["peer.example", "other.org"]
    monkeypatch.delenv("NEXUS_A2A_ALLOWLIST")
    assert a2a_allowlist() == []


def test_host_allowed_matching() -> None:
    assert host_allowed("https://peer.example/api", ["peer.example"]) is True
    assert host_allowed("https://evil.example/api", ["peer.example"]) is False
    assert host_allowed("https://peer.example/api", []) is False


def test_client_blocks_outbound_by_default() -> None:
    client = A2AClient("https://peer.example", transport=lambda *_: (200, "{}"))
    with pytest.raises(PrivacyError):
        client.fetch_card()
    with pytest.raises(PrivacyError):
        client.send_text("hi")


def _fake_peer_transport(card: dict[str, Any], requests: list[dict[str, Any]]):
    """نقل حتمي لوكيل مرجعي: بطاقة من الاكتشاف + رد صدى للرسائل."""
    def transport(url: str, method: str, body: bytes,
                  headers: dict[str, str]) -> tuple[int, str]:
        requests.append({"url": url, "method": method})
        if method == "GET":
            assert url.endswith("/.well-known/agent.json")
            return 200, json.dumps(card)
        req = json.loads(body)
        text = "".join(p["text"] for p in
                       req["params"]["message"]["parts"])
        return 200, json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                "result": {"messageId": "ref-1",
                                           "kind": "message", "role": "agent",
                                           "parts": [{"type": "text",
                                                      "text": f"echo:{text}"}]}})
    return transport


def test_client_sends_to_allowed_peer_only() -> None:
    requests: list[dict[str, Any]] = []
    peer_card = build_hub_card("https://peer.example").to_dict()
    client = A2AClient(
        "https://peer.example", allowlist=["peer.example"],
        transport=_fake_peer_transport(peer_card, requests))
    assert client.reply_text("مرحبا") == "echo:مرحبا"
    # (1) اكتشاف من الجذر ثم (2) إرسال إلى url البطاقة — الترتيب مواصفة.
    assert requests[0]["method"] == "GET"
    assert requests[1]["url"] == peer_card["url"]
    # مضيف شقي داخل نفس العميل = رفض قبل أي نقل.
    rogue = A2AClient("https://evil.example", allowlist=["peer.example"],
                      transport=_fake_peer_transport(peer_card, requests))
    with pytest.raises(PrivacyError):
        rogue.fetch_card()


def test_card_url_outside_allowlist_is_blocked_no_ssrf() -> None:
    """بطاقة ماكرة تُوجه الإرسال لمضيف غير مسموح — الصادر يُرفض."""
    requests: list[dict[str, Any]] = []
    card = build_hub_card("https://evil.example").to_dict()
    client = A2AClient(
        "https://trusted.example", allowlist=["trusted.example"],
        transport=_fake_peer_transport(card, requests))
    with pytest.raises(PrivacyError):
        client.send_text("hi")


def test_client_surfaces_jsonrpc_error() -> None:
    requests: list[dict[str, Any]] = []

    def transport(url: str, method: str, body: bytes,
                  headers: dict[str, str]) -> tuple[int, str]:
        requests.append({"url": url, "method": method})
        if method == "GET":
            return 200, json.dumps(
                build_hub_card("https://peer.example").to_dict())
        req = json.loads(body)
        return 200, json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                "error": {"code": -32601,
                                          "message": "no"}})

    client = A2AClient("https://peer.example", allowlist=["peer.example"],
                       transport=transport)
    with pytest.raises(RuntimeError, match="A2A error"):
        client.reply_text("x")
    assert requests


# ═══ 5. Conformance — دورة كاملة عبر HTTP بلا شبكة ═══════════════════════════════


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app)


def test_well_known_card_endpoint(http: TestClient) -> None:
    r = http.get("/.well-known/agent.json")
    assert r.status_code == 200
    assert validate_card(r.json()) == []


def test_cards_endpoint_serves_fleet(http: TestClient) -> None:
    r = http.get("/api/a2a/cards")
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == len(body["cards"]) >= 100
    assert all(validate_card(c) == [] for c in body["cards"])


def test_message_endpoint_jsonrpc(http: TestClient) -> None:
    r = http.post("/api/a2a/message", json={
        "jsonrpc": "2.0", "id": 42, "method": "message/send",
        "params": {"message": _user_message("تاريخ اليوم؟")}})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 42 and "result" in body
    assert body["result"]["role"] == "agent"


def test_conformance_full_cycle_discover_send_reply(
    http: TestClient,
) -> None:
    """بوابة خروج م4 حرفيًا: اكتشاف → رسالة → رد، عبر عميل A2A حقيقي
    نحوه — نقل مُحقن على TestClient (صفر شبكة، صفر اعتماديات)."""
    def testserver_transport(url: str, method: str, body: bytes,
                             headers: dict[str, str]) -> tuple[int, str]:
        path = url.split("testserver", 1)[1]
        if method == "GET":
            r = http.get(path)
        else:
            r = http.post(path, content=body,
                          headers={"Content-Type": "application/json"})
        return r.status_code, r.text

    client = A2AClient("http://testserver",
                       allowlist=["testserver"],
                       transport=testserver_transport)

    # (1) اكتشاف: بطاقة قياسية صالحة من المسار الشهير.
    card = client.fetch_card()
    assert validate_card(card) == []
    assert card["name"] == "nexus-core"

    # (2) رسالة + (3) رد: دورة message/send كاملة.
    reply = client.reply_text("conformance-probe", request_id=99)
    assert "nexus-core" in reply
    assert A2A_PROTOCOL_VERSION in reply


def test_conformance_reference_fixture_exchange() -> None:
    """تبادل فعلي مع البطاقة المرجعية المُخزَّنة: اكتشاف يخدم فكستشر
    البطاقة المرجعية، ثم إرسال إلى url البطاقة نفسه (مواصفة حقيقية)."""
    peer = json.loads(FIXTURE_CARD.read_text(encoding="utf-8"))
    peer_host = urlsplit_host(peer["url"])
    seen: list[dict[str, Any]] = []

    def peer_transport(url: str, method: str, body: bytes,
                       headers: dict[str, str]) -> tuple[int, str]:
        seen.append({"url": url, "method": method})
        if method == "GET":
            return 200, FIXTURE_CARD.read_text(encoding="utf-8")
        req = json.loads(body)
        text = "".join(p["text"] for p in
                       req["params"]["message"]["parts"])
        return 200, json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                "result": {"messageId": "ref-1",
                                           "kind": "message", "role": "agent",
                                           "parts": [{"type": "text",
                                                      "text": f"echo:{text}"}]}})

    client = A2AClient("https://reference.example",
                       allowlist=[peer_host], transport=peer_transport)
    # (1) البطاقة المرجعية نفسها تُقرأ وتكون صالحة بالمواصفة.
    card = client.fetch_card()
    assert validate_card(card) == []
    assert card == peer
    # (2) الإرسال يذهب حرفيًا إلى url البطاقة المرجعية — لا غير.
    out = client.reply_text("ping", request_id=5)
    assert out == "echo:ping"
    assert seen[-1]["url"] == peer["url"] and seen[-1]["method"] == "POST"


def urlsplit_host(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower()
