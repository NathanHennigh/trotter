"""Instagram caption parsing for Dreams."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_FALLBACK_MODEL = "qwen3.5:27b"

ALLOWED_CATEGORIES = {
    "restaurant",
    "cafe",
    "bar",
    "hotel",
    "attraction",
    "activity",
    "beach",
    "shopping",
    "nature",
    "museum",
    "event",
    "unknown",
}

SYSTEM_PROMPT = """/no_think
You extract travel data from Instagram captions for a travel app.

Return exactly one valid JSON object only. No markdown. No explanations. No reasoning.

Schema for one place:
{
  "category": "restaurant | cafe | bar | hotel | attraction | activity | beach | shopping | nature | museum | event | unknown",
  "place_name": string | null,
  "city": string | null,
  "country": string | null,
  "region_or_neighborhood": string | null,
  "summary": string,
  "tags": string[],
  "google_maps_search_query": string | null,
  "confidence": number,
  "needs_google_places_lookup": boolean,
  "needs_review": boolean
}

Schema for multiple places:
{"items": [same object schema as above]}

Critical rules:
- Never invent an exact place name.
- A city, country, region, neighborhood, or broad destination is NOT a place_name.
- Disable thinking. Do not spend tokens on reasoning. Output the JSON directly.
- If the caption only gives a city, country, region, neighborhood, or general travel vibe, set place_name to null.
- If the caption describes a whole city, country, region, neighborhood, or general travel vibe without naming a specific venue, landmark, event, business, beach, activity, hotel, cafe, bar, or restaurant, set category to "unknown", needs_review to true, and confidence to 0.65 or lower.
- If place_name is null, google_maps_search_query should usually be null.
- If the exact place is unclear or ambiguous, needs_review must be true.
- If an exact place is present, google_maps_search_query should include place + city + country when available.
- confidence must be 0 to 1. Use lower confidence for vague captions.
"""


class DreamParseItem(BaseModel):
    category: str = "unknown"
    place_name: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    region_or_neighborhood: Optional[str] = None
    summary: str = "Saved from Instagram"
    tags: list[str] = Field(default_factory=list)
    google_maps_search_query: Optional[str] = None
    confidence: float = 0.0
    needs_google_places_lookup: bool = False
    needs_review: bool = True


class DreamParseResponse(BaseModel):
    items: list[DreamParseItem]
    model: str
    provider: str = "ollama"
    raw: dict[str, Any] | None = None


class DreamParserError(RuntimeError):
    pass


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def _caption_supports(value: Optional[str], caption: str) -> bool:
    if not value:
        return False
    normalized_value = re.sub(r"\s+", " ", value).strip().lower()
    normalized_caption = re.sub(r"\s+", " ", caption).strip().lower()
    return normalized_value in normalized_caption


def _clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _normalize_item(raw_item: dict[str, Any], caption: str) -> DreamParseItem:
    category = raw_item.get("category") if raw_item.get("category") in ALLOWED_CATEGORIES else "unknown"
    place_name = raw_item.get("place_name") or None
    city = raw_item.get("city") or None
    country = raw_item.get("country") or None
    region = raw_item.get("region_or_neighborhood") or None
    tags = raw_item.get("tags") if isinstance(raw_item.get("tags"), list) else []
    tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()][:12]
    confidence = _clamp_confidence(raw_item.get("confidence"))
    needs_review = bool(raw_item.get("needs_review", True))

    if place_name and city and place_name.strip().lower() == city.strip().lower():
        place_name = None
        needs_review = True
        confidence = min(confidence, 0.65)

    if place_name and not _caption_supports(place_name, caption):
        needs_review = True
        confidence = min(confidence, 0.65)

    if city and not _caption_supports(city, caption):
        needs_review = True
        confidence = min(confidence, 0.75)

    if country and not _caption_supports(country, caption):
        needs_review = True
        confidence = min(confidence, 0.75)

    if not place_name:
        needs_review = True
        confidence = min(confidence, 0.65)
        google_query = None
        needs_google = False
    else:
        google_query = raw_item.get("google_maps_search_query") or " ".join(
            part for part in [place_name, city, country] if part
        )
        needs_google = bool(raw_item.get("needs_google_places_lookup", bool(city or country)))

    summary = str(raw_item.get("summary") or "").strip()
    if not summary:
        summary = re.sub(r"\s+", " ", caption).strip()[:220] or "Saved from Instagram"

    return DreamParseItem(
        category=category,
        place_name=place_name,
        city=city,
        country=country,
        region_or_neighborhood=region,
        summary=summary[:500],
        tags=tags,
        google_maps_search_query=google_query,
        confidence=confidence,
        needs_google_places_lookup=needs_google,
        needs_review=needs_review,
    )


def _normalize_model_output(payload: dict[str, Any], caption: str) -> list[DreamParseItem]:
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else [payload]
    items = [
        _normalize_item(item, caption)
        for item in raw_items
        if isinstance(item, dict)
    ]
    if not items:
        raise DreamParserError("Parser returned no usable items")
    return items


def _fallback_needs_review_response(
    caption: str,
    *,
    model: str,
    error: str,
) -> DreamParseResponse:
    summary = re.sub(r"\s+", " ", caption).strip()[:500] or "Saved from Instagram"
    return DreamParseResponse(
        items=[
            DreamParseItem(
                category="unknown",
                place_name=None,
                summary=summary,
                tags=[],
                confidence=0.0,
                needs_google_places_lookup=False,
                needs_review=True,
            )
        ],
        model=model,
        raw={"parser_error": error},
    )


def fallback_needs_review_response(
    summary: str,
    *,
    model: Optional[str] = None,
    error: str,
) -> DreamParseResponse:
    selected_model = model or os.getenv("DREAM_PARSER_MODEL", DEFAULT_MODEL)
    return _fallback_needs_review_response(summary, model=selected_model, error=error)


def _ollama_chat(
    payload: dict[str, Any],
    ollama_base_url: str,
    timeout: float,
) -> dict[str, Any]:
    try:
        response = httpx.post(f"{ollama_base_url}/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DreamParserError(f"Ollama parser request failed: {exc}") from exc
    return response.json()


def _repair_json_with_ollama(
    bad_content: str,
    *,
    model: str,
    ollama_base_url: str,
    timeout: float,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return exactly one valid JSON object only. No markdown. No explanations.",
            },
            {
                "role": "user",
                "content": f"Repair this into valid JSON without changing field meanings:\n{bad_content}",
            },
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0,
            "num_ctx": 2048,
            "num_predict": 500,
        },
    }
    body = _ollama_chat(payload, ollama_base_url, timeout)
    content = body.get("message", {}).get("content")
    if not isinstance(content, str):
        raise DreamParserError("Ollama JSON repair response did not include message content")
    try:
        return _extract_json_object(content)
    except json.JSONDecodeError as exc:
        raise DreamParserError("Ollama parser returned invalid JSON") from exc


def parse_caption_with_ollama(
    caption: str,
    source_url: Optional[str] = None,
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
) -> DreamParseResponse:
    """Parse an Instagram caption through local Ollama and validate the output."""
    clean_caption = caption.strip()
    if not clean_caption:
        raise DreamParserError("caption is required")

    selected_model = model or os.getenv("DREAM_PARSER_MODEL", DEFAULT_MODEL)
    ollama_base_url = (base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)).rstrip("/")
    timeout = timeout_seconds or float(os.getenv("DREAM_PARSER_TIMEOUT_SECONDS", "20"))

    user_content = "\n".join(
        part
        for part in [
            "/no_think",
            f"Source URL: {source_url}" if source_url else None,
            "Caption:",
            clean_caption,
            "",
            "Return the JSON object now.",
        ]
        if part is not None
    )
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0,
            "num_ctx": 2048,
            "num_predict": 400,
            "repeat_penalty": 1.05,
        },
    }

    body = _ollama_chat(payload, ollama_base_url, timeout)
    content = body.get("message", {}).get("content")
    if not isinstance(content, str):
        raise DreamParserError("Ollama parser response did not include message content")

    try:
        parsed = _extract_json_object(content)
    except json.JSONDecodeError as exc:
        try:
            parsed = _repair_json_with_ollama(
                content,
                model=selected_model,
                ollama_base_url=ollama_base_url,
                timeout=timeout,
            )
        except DreamParserError as repair_error:
            return _fallback_needs_review_response(
                clean_caption,
                model=selected_model,
                error=str(repair_error),
            )

    return DreamParseResponse(
        items=_normalize_model_output(parsed, clean_caption),
        model=selected_model,
        raw=body,
    )


def should_try_stronger_model(result: DreamParseResponse) -> bool:
    first = result.items[0] if result.items else None
    if not first:
        return True
    if first.confidence < 0.55:
        return True
    if first.category == "unknown" and not first.place_name:
        return True
    return False


def parse_caption_with_fallback_model(
    caption: str,
    source_url: Optional[str] = None,
    *,
    primary_model: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> DreamParseResponse:
    primary = parse_caption_with_ollama(caption, source_url, model=primary_model)
    if not should_try_stronger_model(primary):
        return primary

    selected_fallback = fallback_model or os.getenv("DREAM_PARSER_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)
    if selected_fallback == primary.model:
        return primary

    try:
        fallback = parse_caption_with_ollama(caption, source_url, model=selected_fallback)
    except DreamParserError:
        return primary

    if fallback.items and fallback.items[0].confidence > primary.items[0].confidence:
        fallback.raw = {
            **(fallback.raw or {}),
            "fallback_from_model": primary.model,
        }
        return fallback
    return primary
