"""STRIDE — **S**poofing: forging identity / pretending to be another principal.

Attack surface for nexus-core:

* The unified gateway authenticates a *shared secret* (``NEXUS_AUTH_TOKEN``)
  presented in ``X-Auth-Token``. Spoofing = presenting a value that passes the
  comparison without knowing the secret (timing leak, type confusion, empty
  match, header smuggling).
* ``/api/chat`` and ``/api/council/*`` let the *caller name the agent*. If an
  unknown agent id is silently accepted, the caller effectively impersonates a
  privileged persona; if a hostile name is reflected into the system prompt,
  the caller spoofs the agent's identity to the model.
* The client IP used for rate-limit keying comes from the transport; a
  forwarded header must not be trusted blindly (IP spoofing → limit evasion).

Each test states the exploit in its docstring and asserts the *defence*.
"""
from __future__ import annotations

import inspect

import pytest

from tests.security.stride import helpers as H

CATEGORY = "Spoofing"


# ---------------------------------------------------------------------------
# S1 — token comparison must be constant-time (no timing side channel)
# ---------------------------------------------------------------------------
def test_s1_token_compare_is_constant_time() -> None:
    """EXPLOIT: an attacker guesses the token byte-by-byte by measuring response
    latency of a naive ``==`` comparison.

    DEFENCE: the guard must use ``hmac.compare_digest`` (constant time). The
    PoC asserts the *source* uses it AND that a wrong-but-same-length token is
    rejected — proving the guard does not short-circuit on a matching prefix.
    """
    import src.security.access as access_mod

    src = inspect.getsource(access_mod.AccessGuard.check)
    assert "compare_digest" in src, "token compare is not constant-time"

    guard = H.access_guard(token="s3cr3t-token")
    # Same length, matching prefix, wrong tail — a timing attack's favourite.
    dec = guard.check("POST", "/api/chat", {"x-auth-token": "s3cr3t-tokeX"})
    assert dec.allowed is False
    assert dec.status == 401


# ---------------------------------------------------------------------------
# S2 — empty / whitespace token must not authenticate
# ---------------------------------------------------------------------------
def test_s2_empty_and_blank_tokens_never_authenticate() -> None:
    """EXPLOIT: attacker sends ``X-Auth-Token: `` (empty) or whitespace hoping
    the guard treats "no value" as "no check" and lets a write through.

    DEFENCE: when auth is enabled, a missing/blank header is a 401, never a
    pass. Also proves a header bag that is not a mapping cannot crash the
    guard into allowing the request.
    """
    guard = H.access_guard(token="real-token")
    for header in ("", "   ", None):
        headers = {} if header is None else {"x-auth-token": header}
        dec = guard.check("POST", "/api/chat", headers)
        assert dec.allowed is False, f"blank token {header!r} was accepted"
        assert dec.status == 401

    # A hostile header object (attribute access raises) must fail closed.
    class Hostile:
        def get(self, *_a: object) -> str:
            raise AttributeError("boom")

    dec = guard.check("POST", "/api/chat", Hostile())
    assert dec.allowed is False


# ---------------------------------------------------------------------------
# S3 — a wrong token cannot be smuggled via a different header spelling
# ---------------------------------------------------------------------------
def test_s3_header_spelling_is_exact() -> None:
    """EXPLOIT: attacker sends ``Authorization: Bearer <guess>`` or
    ``X-Auth`` (prefix of the real header) hoping a loose lookup matches.

    DEFENCE: only the exact configured header key is consulted. A near-miss
    header must not authenticate.
    """
    guard = H.access_guard(token="right", header="x-auth-token")
    for wrong_header in ("authorization", "x-auth", "x-auth-tokens", "token"):
        dec = guard.check("POST", "/api/chat", {wrong_header: "right"})
        assert dec.allowed is False, f"header {wrong_header!r} authenticated"


# ---------------------------------------------------------------------------
# S4 — unknown agent id must not be silently granted a privileged persona
# ---------------------------------------------------------------------------
def test_s4_unknown_agent_does_not_impersonate_a_known_agent() -> None:
    """EXPLOIT: caller posts ``{"agent": "../../system"}}`` or a name colliding
    with a privileged agent to spoof its persona in the prompt.

    DEFENCE: the roster is a closed set (``all_manifests()``). An unknown /
    path-like / case-flipped id must be **absent** from it and
    ``get_manifest`` must refuse it (KeyError), never fall back to another
    agent's identity.
    """
    pytest.importorskip("src.agents.manifest")
    from src.agents.manifest import all_manifests, get_manifest

    roster = all_manifests()
    for hostile in ("../coder", "coder/../tester", "coder\x00", "CODER", "**"):
        assert hostile not in roster, (
            f"hostile agent id {hostile!r} is a real roster key"
        )
        with pytest.raises(KeyError):
            get_manifest(hostile)


# ---------------------------------------------------------------------------
# S5 — the client key for rate-limiting must not trust a spoofed header
# ---------------------------------------------------------------------------
def test_s5_client_key_ignores_forwarded_headers() -> None:
    """EXPLOIT: attacker varies ``X-Forwarded-For`` on every request to get a
    fresh rate-limit bucket, defeating the throttle (IP spoofing).

    DEFENCE: the guard's key is built from the *transport* client value passed
    by the ASGI layer; it must not read forwarded headers from the header bag.
    The PoC passes a header bag full of spoofed IPs and asserts the limiter
    still counts them under the same key.
    """
    from src.security.access import RateLimiter

    limiter = RateLimiter(rate=2, window=60.0, clock=lambda: 0.0)
    key = "127.0.0.1|POST|/api/chat"
    allowed = [limiter.allow(key) for _ in range(3)]
    # 3rd call exceeds rate=2 → must be refused, regardless of any headers.
    assert allowed[0] == 0.0 and allowed[1] == 0.0
    assert allowed[2] > 0.0, "rate limit evaded (spoofable client key)"

    # And the guard itself keys on the caller-supplied client arg, not headers.
    guard = H.access_guard(token="", limiter=RateLimiter(rate=1, window=60.0,
                                                         clock=lambda: 0.0))
    spoof = {"x-forwarded-for": "10.0.0.1"}
    assert guard.check("POST", "/api/x", spoof, client="127.0.0.1").allowed
    second = guard.check("POST", "/api/x", {"x-forwarded-for": "10.0.0.2"},
                         client="127.0.0.1")
    assert second.allowed is False, "rotating X-Forwarded-For reset the bucket"
