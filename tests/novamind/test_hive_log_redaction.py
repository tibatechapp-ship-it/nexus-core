"""يتأكد أن أي سر في logs يتم redact."""
import logging
from novamind.core.hive.security.log_redaction import RedactingFilter, REPLACEMENT


def _make_record(msg):
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )


def test_telegram_token_redacted():
    f = RedactingFilter()
    r = _make_record("https://api.telegram.org/bot123456789:ABCdef_GHIjkl-MNOpqr/getMe")
    f.filter(r)
    assert REPLACEMENT in r.msg
    assert "bot123456789" not in r.msg


def test_mistral_key_redacted():
    f = RedactingFilter()
    r = _make_record("key=mstrl_abcdefghijklmnopqrstuvwx")
    f.filter(r)
    assert REPLACEMENT in r.msg


def test_groq_key_redacted():
    f = RedactingFilter()
    r = _make_record("Authorization: Bearer gsk_abcdefghijklmnopqrstu")
    f.filter(r)
    assert REPLACEMENT in r.msg


def test_github_pat_redacted():
    f = RedactingFilter()
    r = _make_record("token=ghp_abcdefghijklmnopqrstuv")
    f.filter(r)
    assert REPLACEMENT in r.msg


def test_clean_message_untouched():
    f = RedactingFilter()
    r = _make_record("just a normal log line")
    f.filter(r)
    assert r.msg == "just a normal log line"
