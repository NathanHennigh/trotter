"""Tests for Instagram metadata extraction."""

from __future__ import annotations

import httpx

from app.services import instagram_metadata


def test_canonical_instagram_url_removes_share_query():
    assert (
        instagram_metadata.canonical_instagram_url(
            "https://www.instagram.com/reel/DQnavBEEXF4/?igsh=MWc4NWlpMnVlampnZQ=="
        )
        == "https://instagram.com/reel/DQnavBEEXF4"
    )


def test_oembed_instagram_url_uses_www_and_trailing_slash():
    assert (
        instagram_metadata.oembed_instagram_url(
            "https://instagram.com/reel/DQnavBEEXF4?igsh=MWc4NWlpMnVlampnZQ=="
        )
        == "https://www.instagram.com/reel/DQnavBEEXF4/"
    )


def test_extract_instagram_metadata_from_open_graph_html():
    html = """
    <html>
      <head>
        <meta property="og:title" content="Creator on Instagram" />
        <meta property="og:description" content="1,234 likes, 10 comments - Creator on Instagram: &quot;Casa Dani in Madrid, Spain. Best tortilla.&quot;" />
        <meta property="og:image" content="https://cdn.example.com/thumb.jpg" />
      </head>
    </html>
    """

    metadata = instagram_metadata.extract_instagram_metadata_from_html(
        "https://www.instagram.com/reel/test/",
        html,
    )

    assert metadata.fetched is True
    assert metadata.caption == '"Casa Dani in Madrid, Spain. Best tortilla."'
    assert metadata.thumbnail_url == "https://cdn.example.com/thumb.jpg"


def test_fetch_instagram_metadata_uses_browserish_headers(monkeypatch):
    captured = {}

    def fake_get(url, headers, follow_redirects, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["follow_redirects"] = follow_redirects
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            html="""
            <meta property="og:description" content="Creator on Instagram: Lisbon cafe list" />
            """,
        )

    monkeypatch.setattr(instagram_metadata.httpx, "get", fake_get)

    metadata = instagram_metadata.fetch_instagram_metadata("https://www.instagram.com/reel/test/")

    assert captured["url"] == "https://instagram.com/reel/test"
    assert "Mozilla" in captured["headers"]["User-Agent"]
    assert captured["follow_redirects"] is True
    assert metadata.caption == "Lisbon cafe list"


def test_fetch_instagram_metadata_falls_back_to_oembed(monkeypatch):
    calls = []

    def fake_get(url, headers, follow_redirects, timeout):
        calls.append(url)
        if "api/v1/oembed" in url:
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={
                    "title": "This place in Guatemala was a dream\n\nAmate Atitlan, Lake Atitlan",
                    "thumbnail_url": "https://cdn.example.com/thumb.jpg",
                },
            )
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text="<html><title>Instagram</title></html>",
        )

    monkeypatch.setattr(instagram_metadata.httpx, "get", fake_get)

    metadata = instagram_metadata.fetch_instagram_metadata("https://www.instagram.com/reel/test/")

    assert calls[0] == "https://instagram.com/reel/test"
    assert calls[1].endswith("url=https%3A%2F%2Fwww.instagram.com%2Freel%2Ftest%2F")
    assert metadata.caption == "This place in Guatemala was a dream Amate Atitlan, Lake Atitlan"
    assert metadata.thumbnail_url == "https://cdn.example.com/thumb.jpg"
