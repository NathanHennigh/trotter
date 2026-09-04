"""Tests for the provider-neutral Dreams parser."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services import dream_parser


def parsed_place(**overrides):
    item = {
        "category": "restaurant",
        "place_name": "Casa Dani",
        "city": "Madrid",
        "country": "Spain",
        "region_or_neighborhood": None,
        "summary": "Tortilla spot in Madrid.",
        "tags": ["food"],
        "google_maps_search_query": "Casa Dani Madrid Spain",
        "confidence": 0.94,
        "needs_google_places_lookup": True,
        "needs_review": False,
    }
    item.update(overrides)
    return item


def venice_response(url: str, *, item=None, status_code: int = 200, headers=None):
    body = {
        "id": "chatcmpl-test",
        "model": "qwen3-5-9b",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps({"items": [item or parsed_place()]})},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    return httpx.Response(
        status_code, request=httpx.Request("POST", url), headers=headers, json=body
    )


def test_parse_caption_with_venice_uses_schema_and_sanitizes_metadata(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return venice_response(url, headers={"cf-ray": "test-ray"})

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_venice(
        "Casa Dani\nBest tortilla in Madrid, Spain.",
        "https://instagram.com/reel/test",
        api_key="venice-test-key",
        max_attempts=1,
    )

    assert captured["url"] == "https://api.venice.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer venice-test-key"
    assert captured["json"]["model"] == "qwen3-5-9b"
    assert captured["json"]["response_format"]["type"] == "json_schema"
    assert captured["json"]["response_format"]["json_schema"]["strict"] is True
    assert captured["json"]["parallel_tool_calls"] is False
    assert captured["json"]["venice_parameters"]["enable_web_search"] == "off"
    assert captured["json"]["venice_parameters"]["include_venice_system_prompt"] is False
    assert result.model == "qwen3-5-9b"
    assert result.provider == "venice"
    assert result.items[0].place_name == "Casa Dani"
    assert result.items[0].needs_review is False
    assert result.raw["prompt_version"] == "dream-places-v2"
    assert result.raw["attempts"] == 1
    assert result.raw["latency_ms"] >= 0
    assert result.raw["request_id"] == "chatcmpl-test"
    assert result.raw["provider_model"] == "qwen3-5-9b"
    assert result.raw["finish_reason"] == "stop"
    assert result.raw["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    assert result.raw["cf_ray"] == "test-ray"
    assert "venice-test-key" not in json.dumps(result.raw)
    assert "choices" not in result.raw


def test_parse_caption_defaults_to_venice(monkeypatch):
    captured = {}

    def fake_venice(caption, source_url=None, **kwargs):
        captured.update(caption=caption, source_url=source_url, kwargs=kwargs)
        return dream_parser.DreamParseResponse(
            items=[dream_parser.DreamParseItem(summary="ok")], model="qwen3-5-9b", provider="venice"
        )

    monkeypatch.delenv("DREAM_AI_PROVIDER", raising=False)
    monkeypatch.setattr(dream_parser, "parse_caption_with_venice", fake_venice)

    result = dream_parser.parse_caption("Madrid travel list", "https://instagram.com/p/test")

    assert result.provider == "venice"
    assert captured["source_url"] == "https://instagram.com/p/test"


def test_parse_caption_with_venice_requires_server_key(monkeypatch):
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    monkeypatch.delenv("VENICE_API_KEY_FILE", raising=False)

    with pytest.raises(dream_parser.DreamParserConfigurationError, match="not configured"):
        dream_parser.parse_caption_with_venice("Madrid travel list", max_attempts=1)


def test_parse_caption_with_venice_reads_key_file(monkeypatch, tmp_path):
    key_file = tmp_path / "venice_api_key"
    key_file.write_text("file-key\n", encoding="utf-8")
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["authorization"] = headers["Authorization"]
        return venice_response(url)

    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    monkeypatch.setenv("VENICE_API_KEY_FILE", str(key_file))
    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    dream_parser.parse_caption_with_venice("Casa Dani in Madrid, Spain.", max_attempts=1)

    assert captured["authorization"] == "Bearer file-key"


def test_parse_caption_with_venice_retries_transient_failure(monkeypatch):
    calls = []
    sleeps = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        if len(calls) == 1:
            return httpx.Response(
                503, request=httpx.Request("POST", url), headers={"retry-after": "0"}
            )
        return venice_response(url)

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)
    monkeypatch.setattr(dream_parser.time, "sleep", sleeps.append)

    result = dream_parser.parse_caption_with_venice(
        "Casa Dani in Madrid, Spain.", api_key="test-key", max_attempts=2
    )

    assert len(calls) == 2
    assert sleeps == [0.0]
    assert result.items[0].place_name == "Casa Dani"
    assert result.raw["attempts"] == 2


def test_parse_caption_with_venice_does_not_retry_configuration_failure(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    with pytest.raises(dream_parser.DreamParserConfigurationError, match="HTTP 401"):
        dream_parser.parse_caption_with_venice(
            "Casa Dani in Madrid, Spain.", api_key="bad-key", max_attempts=2
        )

    assert len(calls) == 1


def test_parse_caption_with_venice_preserves_multiple_places(monkeypatch):
    def fake_post(url, headers, json, timeout):
        response = venice_response(url)
        body = response.json()
        body["choices"][0]["message"]["content"] = json_module.dumps(
            {
                "items": [
                    parsed_place(),
                    parsed_place(
                        category="cafe",
                        place_name="Hola Coffee",
                        summary="Coffee shop in Madrid.",
                        google_maps_search_query="Hola Coffee Madrid Spain",
                    ),
                ]
            }
        )
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    json_module = json
    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_venice(
        "Casa Dani and Hola Coffee in Madrid, Spain.", api_key="test-key", max_attempts=1
    )

    assert [item.place_name for item in result.items] == ["Casa Dani", "Hola Coffee"]


def test_parse_caption_with_venice_rejects_truncated_output(monkeypatch):
    def fake_post(url, headers, json, timeout):
        response = venice_response(url)
        body = response.json()
        body["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    with pytest.raises(dream_parser.DreamParserError, match="finish reason: length"):
        dream_parser.parse_caption_with_venice(
            "Casa Dani in Madrid, Spain.", api_key="test-key", max_attempts=1
        )


def test_parse_caption_with_ollama_uses_local_default_and_normalizes(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"message": {"content": json_module.dumps(parsed_place())}},
        )

    json_module = json
    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama(
        "Casa Dani\nBest tortilla in Madrid, Spain.", "https://instagram.com/reel/test"
    )

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["model"] == "qwen3.5:4b"
    assert captured["json"]["format"] == "json"
    assert captured["json"]["options"]["temperature"] == 0
    assert result.model == "qwen3.5:4b"
    assert result.provider == "ollama"
    assert result.items[0].place_name == "Casa Dani"


def test_parse_caption_caps_unsupported_place_confidence(monkeypatch):
    def fake_post(url, json, timeout):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "message": {"content": json_module.dumps(parsed_place(place_name="Invented Cafe"))}
            },
        )

    json_module = json
    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama(
        "Madrid food list", "https://instagram.com/reel/test"
    )

    assert result.items[0].place_name == "Invented Cafe"
    assert result.items[0].needs_review is True
    assert result.items[0].confidence == 0.65


def test_parse_caption_repairs_invalid_ollama_json_once(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json["messages"][0]["content"])
        if len(calls) == 1:
            content = '{"category":"restaurant","place_name":"Casa Dani","city":"Madrid"'
        else:
            content = json_module.dumps(parsed_place())
        return httpx.Response(
            200, request=httpx.Request("POST", url), json={"message": {"content": content}}
        )

    json_module = json
    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama("Casa Dani in Madrid, Spain.")

    assert len(calls) == 2
    assert result.items[0].place_name == "Casa Dani"
    assert result.raw["json_repaired"] is True


def test_parse_caption_falls_back_to_review_when_ollama_json_repair_fails(monkeypatch):
    def fake_post(url, json, timeout):
        return httpx.Response(
            200, request=httpx.Request("POST", url), json={"message": {"content": "not json"}}
        )

    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama("Some travel reel caption")

    assert result.items[0].place_name is None
    assert result.items[0].needs_review is True
    assert result.items[0].confidence == 0.0
    assert result.provider == "ollama"
    assert "parser_error" in result.raw


def test_parse_caption_forces_city_as_place_to_review(monkeypatch):
    def fake_post(url, json, timeout):
        item = parsed_place(
            category="unknown",
            place_name="Zakynthos",
            city="Zakynthos",
            country="Greece",
            summary="Island trip.",
            confidence=0.85,
        )
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"message": {"content": json_module.dumps(item)}},
        )

    json_module = json
    monkeypatch.setattr(dream_parser.httpx, "post", fake_post)

    result = dream_parser.parse_caption_with_ollama("Zakynthos, Greece travel guide")

    assert result.items[0].place_name is None
    assert result.items[0].needs_review is True
    assert result.items[0].confidence == 0.65


def test_fallback_model_uses_kimi_when_primary_is_weak(monkeypatch):
    calls = []

    def fake_parse(caption, source_url=None, provider=None, model=None, **kwargs):
        calls.append((provider, model))
        if model == "kimi-k2-5":
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
                model=model,
                provider="venice",
            )
        return dream_parser.DreamParseResponse(
            items=[dream_parser.DreamParseItem(category="unknown", summary="weak", confidence=0.2)],
            model=model,
            provider="venice",
        )

    monkeypatch.setattr(dream_parser, "parse_caption", fake_parse)

    result = dream_parser.parse_caption_with_fallback_model(
        "vague caption", provider="venice", primary_model="qwen3-5-9b", fallback_model="kimi-k2-5"
    )

    assert calls == [("venice", "qwen3-5-9b"), ("venice", "kimi-k2-5")]
    assert result.model == "kimi-k2-5"
    assert result.items[0].place_name == "Onera"
    assert result.raw["fallback_from_model"] == "qwen3-5-9b"
    assert result.raw["fallback_reason"] == "weak_primary"


def test_fallback_model_recovers_from_primary_request_failure(monkeypatch):
    def fake_parse(caption, source_url=None, provider=None, model=None, **kwargs):
        if model == "qwen3-5-9b":
            raise dream_parser.DreamParserError("temporary primary failure")
        return dream_parser.DreamParseResponse(
            items=[dream_parser.DreamParseItem(summary="Recovered", confidence=0.8)],
            model=model,
            provider="venice",
        )

    monkeypatch.setattr(dream_parser, "parse_caption", fake_parse)

    result = dream_parser.parse_caption_with_fallback_model(
        "Madrid travel list",
        provider="venice",
        primary_model="qwen3-5-9b",
        fallback_model="kimi-k2-5",
    )

    assert result.model == "kimi-k2-5"
    assert result.raw["fallback_reason"] == "primary_error"


def test_configuration_error_does_not_repeat_with_fallback(monkeypatch):
    calls = []

    def fake_parse(*args, **kwargs):
        calls.append(kwargs["model"])
        raise dream_parser.DreamParserConfigurationError("VENICE_API_KEY is not configured")

    monkeypatch.setattr(dream_parser, "parse_caption", fake_parse)

    with pytest.raises(dream_parser.DreamParserConfigurationError, match="not configured"):
        dream_parser.parse_caption_with_fallback_model(
            "Madrid travel list",
            provider="venice",
            primary_model="qwen3-5-9b",
            fallback_model="kimi-k2-5",
        )

    assert calls == ["qwen3-5-9b"]
