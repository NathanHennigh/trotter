"""Tests for the Dreams Ollama parser wrapper."""

from __future__ import annotations

import httpx

from app.services import dream_parser


def test_parse_caption_with_ollama_uses_qwen_default_and_normalizes(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "message": {
                    "content": '{"category":"restaurant","place_name":"Casa Dani","city":"Madrid","country":"Spain","region_or_neighborhood":null,"summary":"Tortilla spot in Madrid.","tags":["food"],"google_maps_search_query":"Casa Dani Madrid Spain","confidence":0.94,"needs_google_places_lookup":true,"needs_review":false}'
                }
            },
        )

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama(
        "Casa Dani\nBest tortilla in Madrid, Spain.",
        "https://instagram.com/reel/test",
    )

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["model"] == "qwen3.5:4b"
    assert captured["json"]["format"] == "json"
    assert captured["json"]["options"]["temperature"] == 0
    assert result.model == "qwen3.5:4b"
    assert result.items[0].place_name == "Casa Dani"
    assert result.items[0].needs_review is False


def test_parse_caption_caps_unsupported_place_confidence(monkeypatch):
    def fake_post(url, json, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "message": {
                    "content": '{"category":"restaurant","place_name":"Invented Cafe","city":"Madrid","country":"Spain","summary":"A cafe.","tags":[],"google_maps_search_query":"Invented Cafe Madrid Spain","confidence":0.99,"needs_google_places_lookup":true,"needs_review":false}'
                }
            },
        )

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama("Madrid food list", "https://instagram.com/reel/test")

    assert result.items[0].place_name == "Invented Cafe"
    assert result.items[0].needs_review is True
    assert result.items[0].confidence == 0.65


def test_parse_caption_repairs_invalid_json_once(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json["messages"][0]["content"])
        if len(calls) == 1:
            content = '{"category":"restaurant","place_name":"Casa Dani","city":"Madrid"'
        else:
            content = '{"category":"restaurant","place_name":"Casa Dani","city":"Madrid","country":"Spain","summary":"Tortilla spot.","tags":[],"confidence":0.9,"needs_google_places_lookup":true,"needs_review":false}'
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"message": {"content": content}},
        )

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama("Casa Dani in Madrid, Spain.")

    assert len(calls) == 2
    assert result.items[0].place_name == "Casa Dani"
    assert result.items[0].needs_review is False


def test_parse_caption_falls_back_to_review_when_json_repair_fails(monkeypatch):
    def fake_post(url, json, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"message": {"content": "not json"}},
        )

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama("Some travel reel caption")

    assert result.items[0].place_name is None
    assert result.items[0].needs_review is True
    assert result.items[0].confidence == 0.0
    assert "parser_error" in result.raw


def test_parse_caption_forces_city_as_place_to_review(monkeypatch):
    def fake_post(url, json, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "message": {
                    "content": '{"category":"unknown","place_name":"Zakynthos","city":"Zakynthos","country":"Greece","summary":"Island trip.","tags":[],"confidence":0.85,"needs_google_places_lookup":true,"needs_review":false}'
                }
            },
        )

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama("Zakynthos, Greece travel guide")

    assert result.items[0].place_name is None
    assert result.items[0].needs_review is True
    assert result.items[0].confidence == 0.65


def test_parse_caption_with_fallback_model_uses_27b_when_primary_is_weak(monkeypatch):
    calls = []

    def fake_parse(caption, source_url=None, model=None, **kwargs):
        calls.append(model)
        if model == "qwen3.5:27b":
            return dream_parser.DreamParseResponse(
                items=[
                    dream_parser.DreamParseItem(
                        category="hotel",
                        place_name="Onera",
                        city="Wimberley",
                        country="United States",
                        summary="Cabin stay.",
                        confidence=0.9,
                        needs_review=False,
                    )
                ],
                model="qwen3.5:27b",
            )
        return dream_parser.DreamParseResponse(
            items=[dream_parser.DreamParseItem(category="unknown", summary="weak", confidence=0.2)],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr(dream_parser, "parse_caption_with_ollama", fake_parse)

    result = dream_parser.parse_caption_with_fallback_model("vague caption")

    assert calls == [None, "qwen3.5:27b"]
    assert result.model == "qwen3.5:27b"
    assert result.items[0].place_name == "Onera"
