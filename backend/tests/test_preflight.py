import pytest

from app.preflight import _required


def test_required_rejects_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", " GOCSPX-example-secret\r ")

    with pytest.raises(
        ValueError,
        match="GOOGLE_CLIENT_SECRET must not contain surrounding whitespace",
    ):
        _required("GOOGLE_CLIENT_SECRET")


def test_required_returns_exact_value(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-example-secret")

    assert _required("GOOGLE_CLIENT_SECRET") == "GOCSPX-example-secret"
