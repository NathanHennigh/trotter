import socket

import pytest

from app.services.gmail import _with_backoff


def test_with_backoff_pauses_and_retries_transient_dns_failures(monkeypatch):
    calls = {"count": 0, "slept": []}

    monkeypatch.setenv("TROTTER_GMAIL_NETWORK_RETRY_SECONDS", "30")
    monkeypatch.setattr("app.services.gmail.random.uniform", lambda _a, _b: 0)
    monkeypatch.setattr("app.services.gmail.time.sleep", lambda seconds: calls["slept"].append(seconds))

    def flaky_call():
        calls["count"] += 1
        if calls["count"] == 1:
            raise socket.gaierror(11004, "getaddrinfo failed")
        return {"ok": True}

    assert _with_backoff(flaky_call) == {"ok": True}
    assert calls["count"] == 2
    assert calls["slept"]


def test_with_backoff_raises_network_error_after_retry_budget_exhausted(monkeypatch):
    monkeypatch.setenv("TROTTER_GMAIL_NETWORK_RETRY_SECONDS", "0")

    with pytest.raises(socket.gaierror):
        _with_backoff(lambda: (_ for _ in ()).throw(socket.gaierror(11004, "getaddrinfo failed")))


def test_with_backoff_does_not_retry_revoked_google_token(monkeypatch):
    calls = {"count": 0}

    monkeypatch.setenv("TROTTER_GMAIL_NETWORK_RETRY_SECONDS", "30")
    monkeypatch.setattr("app.services.gmail.time.sleep", lambda _seconds: None)

    class RefreshError(Exception):
        pass

    def revoked_call():
        calls["count"] += 1
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    with pytest.raises(RefreshError):
        _with_backoff(revoked_call)

    assert calls["count"] == 1
