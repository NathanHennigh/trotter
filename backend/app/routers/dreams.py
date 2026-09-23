"""
Dreams endpoints for Instagram share capture and review.
"""

from __future__ import annotations

import re
import math
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Dream, DreamItem, DreamLocation, User
from ..services.dream_parser import (
    DreamParserError,
    DreamParseItem,
    DreamParseResponse,
    fallback_needs_review_response,
    parse_caption_with_fallback_model,
)
from ..services.dream_thumbnail_cache import (
    DreamThumbnailError,
    cache_thumbnail,
    read_cached_thumbnail,
)
from ..services.google_places import (
    GeoapifyError,
    GooglePlacesError,
    build_google_maps_search_url,
    search_geoapify_place,
    search_google_place,
)
from ..services.instagram_metadata import InstagramMetadataError, fetch_instagram_metadata
from ..services.dream_locations import (
    confirm_candidate, enqueue_location, location_coordinates, location_maps_url, public_location,
)
from ..services.dream_enrichment import cancel_enrichment, enqueue_enrichment
from ..tasks.dream_enrichment_tasks import notify_enrichment
from .auth import get_current_user

google_map_capable = ContextVar("dreams_google_map_capable", default=False)


async def private_dream_response(response: Response, request: Request):
    response.headers["Cache-Control"] = "private, no-store"
    token = google_map_capable.set(request.headers.get("X-Trotter-Maps", "").lower() == "google")
    try:
        yield
    finally:
        google_map_capable.reset(token)


router = APIRouter(tags=["dreams"], dependencies=[Depends(private_dream_response)])

KNOWN_COUNTRIES = [
    "France",
    "Spain",
    "Italy",
    "Portugal",
    "Japan",
    "Mexico",
    "Greece",
    "Iceland",
    "Thailand",
    "United Kingdom",
    "South Africa",
    "United States",
]

KNOWN_CITIES = {
    "paris": ("Paris", "France"),
    "madrid": ("Madrid", "Spain"),
    "barcelona": ("Barcelona", "Spain"),
    "rome": ("Rome", "Italy"),
    "lisbon": ("Lisbon", "Portugal"),
    "tokyo": ("Tokyo", "Japan"),
    "kyoto": ("Kyoto", "Japan"),
    "mexico city": ("Mexico City", "Mexico"),
    "athens": ("Athens", "Greece"),
    "reykjavik": ("Reykjavik", "Iceland"),
    "bangkok": ("Bangkok", "Thailand"),
    "london": ("London", "United Kingdom"),
    "cape town": ("Cape Town", "South Africa"),
    "new york": ("New York", "United States"),
    "krabi": ("Krabi", "Thailand"),
}

CATEGORY_KEYWORDS = {
    "restaurant": ["restaurant", "tapas", "dinner", "lunch", "brunch", "tortilla"],
    "cafe": ["cafe", "coffee", "bakery", "pastry"],
    "bar": ["bar", "cocktail", "rooftop"],
    "hotel": ["hotel", "airbnb", "resort", "stay"],
    "beach": ["beach"],
    "museum": ["museum", "gallery"],
    "nature": ["mountain", "glacier", "waterfall", "hike", "trail", "park"],
    "shopping": ["market", "shop", "boutique"],
    "attraction": ["temple", "castle", "tower", "landmark", "viewpoint"],
    "activity": ["tour", "class", "experience", "boat", "surf"],
}


class ShareDreamRequest(BaseModel):
    source_platform: str = "instagram"
    source_url: str = Field(..., min_length=1)
    shared_text: Optional[str] = None
    caption: Optional[str] = None


class ShareDreamResponse(BaseModel):
    dream_item_id: int
    dream_id: int
    status: str
    duplicate: bool = False


class DreamOut(BaseModel):
    id: int
    title: str
    country: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    status: str
    item_count: int = 0
    needs_review_count: int = 0
    processing_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LocationCandidateOut(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    latitude: float
    longitude: float
    google_maps_url: str
    attributions: list[dict[str, str]] = Field(default_factory=list)


class LocateMissingRequest(BaseModel):
    item_ids: Optional[list[int]] = Field(default=None, max_length=1000)


class SortDreamsRequest(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=1000)


class ConfirmLocationRequest(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=4096)


class DreamItemOut(BaseModel):
    id: int
    dream_id: int
    source_platform: str
    source_url: str
    caption: Optional[str] = None
    category: str
    place_name: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    region_or_neighborhood: Optional[str] = None
    summary: str
    tags_json: Optional[list[str]] = None
    confidence: Optional[float] = None
    needs_review: bool
    needs_google_places_lookup: bool
    google_place_id: Optional[str] = None
    google_maps_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    coordinate_precision: Optional[Literal["place", "area"]] = None
    location_status: Optional[Literal["queued", "running", "resolved", "needs_review", "not_found", "failed", "blocked", "manual"]] = None
    location_address: Optional[str] = None
    location_provider: Optional[str] = None
    location_candidates: list[LocationCandidateOut] = Field(default_factory=list)
    location_message: Optional[str] = None
    location_checked_at: Optional[datetime] = None
    location_place_id: Optional[str] = None
    location_candidate_ids: list[str] = Field(default_factory=list)
    location_expires_at: Optional[datetime] = None
    location_user_confirmed: bool = False
    status: str
    processing_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReviewEdits(BaseModel):
    dream_id: Optional[int] = None
    category: Optional[str] = None
    place_name: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    region_or_neighborhood: Optional[str] = None
    summary: Optional[str] = None
    tags_json: Optional[list[str]] = None
    google_place_id: Optional[str] = None
    google_maps_url: Optional[str] = None


class ReviewDreamItemRequest(BaseModel):
    decision: Literal["confirm", "needs_review"] = "confirm"
    edits: Optional[ReviewEdits] = None


class ParseTravelCaptionRequest(BaseModel):
    source_url: Optional[str] = None
    caption: Optional[str] = None


class ParseTravelCaptionBatchRequest(BaseModel):
    source_urls: Optional[list[str]] = None
    links_text: Optional[str] = None


class ParseTravelCaptionBatchResult(BaseModel):
    source_url: str
    ok: bool
    result: Optional[DreamParseResponse] = None
    error: Optional[str] = None


class ParseTravelCaptionBatchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[ParseTravelCaptionBatchResult]


class ImportInstagramBatchRequest(BaseModel):
    source_urls: Optional[list[str]] = None
    links_text: Optional[str] = None


class ImportInstagramBatchResult(BaseModel):
    source_url: str
    dream_item_id: int
    dream_id: int
    status: str
    duplicate: bool = False
    place_name: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    google_maps_url: Optional[str] = None
    needs_review: bool
    note: Optional[str] = None


class ImportInstagramBatchResponse(BaseModel):
    total: int
    imported: int
    duplicates: int
    results: list[ImportInstagramBatchResult]


class ParseDreamItemRequest(BaseModel):
    caption: Optional[str] = None


def normalize_source_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="source_url is required")

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if not parsed.netloc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="source_url must be a URL")

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower() or "https", netloc, path, "", "", ""))


def extract_urls_from_text(value: str) -> list[str]:
    seen = set()
    urls: list[str] = []
    for match in re.findall(r"https?://[^\s<>'\")]+", value):
        cleaned = match.rstrip(".,;]")
        if cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)
    return urls


def batch_source_urls(payload: ParseTravelCaptionBatchRequest) -> list[str]:
    urls = []
    if payload.source_urls:
        urls.extend(payload.source_urls)
    if payload.links_text:
        urls.extend(extract_urls_from_text(payload.links_text))

    normalized = []
    seen = set()
    for url in urls:
        normalized_url = normalize_source_url(url)
        if normalized_url not in seen:
            seen.add(normalized_url)
            normalized.append(normalized_url)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_urls or links_text must include at least one URL",
        )
    return normalized


def infer_category(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "unknown"


def find_location(text: str) -> tuple[Optional[str], Optional[str]]:
    lowered = text.lower()
    city = None
    country = None

    for city_key, (known_city, known_country) in KNOWN_CITIES.items():
        if re.search(rf"\b{re.escape(city_key)}\b", lowered):
            city = known_city
            country = known_country
            break

    for known_country in KNOWN_COUNTRIES:
        if re.search(rf"\b{re.escape(known_country.lower())}\b", lowered):
            country = known_country
            break

    return city, country


def extract_tags(text: str) -> list[str]:
    seen = set()
    tags: list[str] = []
    for match in re.findall(r"#([A-Za-z0-9_]+)", text):
        tag = match.lower()
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags[:12]


def likely_place_name(text: str, city: Optional[str], country: Optional[str]) -> Optional[str]:
    pinned = extract_pinned_place(text)
    if pinned:
        return pinned[0]

    lines = [line.strip(" -\t") for line in text.splitlines() if line.strip()]
    for line in lines:
        if len(line) > 64:
            continue
        lowered = line.lower()
        if city and lowered == city.lower():
            continue
        if country and lowered == country.lower():
            continue
        if any(marker in lowered for marker in ["http", "instagram", "save this", "your sign"]):
            continue
        if re.search(r"[A-Z][A-Za-z0-9'&.]+(?:\s+[A-Z][A-Za-z0-9'&.]+){0,4}", line):
            return line
    return None


def extract_pinned_place(text: str) -> Optional[tuple[str, Optional[str]]]:
    """Extract common social-caption patterns like `📍 Place Name, City`."""
    match = re.search(
        r"(?:📍|(?:\b(?:location|spot|place)\s*[:\-]))\s*"
        r"(?P<place>[A-Z][A-Za-z0-9'&. -]{1,80}?)"
        r"(?:,\s*(?P<city>[A-Z][A-Za-z' .-]{1,60}))?"
        r"(?=\s+(?:tag|the|this|best|#)|$)",
        text,
    )
    if not match:
        match = re.search(
            r"(?P<place>[A-Z][A-Za-z0-9'&. -]{1,80}\b(?:Cafe|Restaurant|Hotel|Bar|Resort|Beach))"
            r",\s*(?P<city>[A-Z][A-Za-z' .-]{1,60})"
            r"(?=\s+(?:tag|the|this|best|#)|$)",
            text,
        )
    if not match:
        return None

    place = match.group("place").strip(" -,.")
    city = match.group("city")
    return place, city.strip(" -,.") if city else None


def summarize(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return "Saved from Instagram"
    return compact[:220]


def is_url_only_text(value: Optional[str], source_url: Optional[str] = None) -> bool:
    if not value:
        return False
    compact = value.strip()
    if not compact:
        return False
    without_urls = re.sub(r"https?://\S+", "", compact, flags=re.IGNORECASE).strip()
    if without_urls:
        return False
    return True


def usable_caption_text(caption: Optional[str], source_url: Optional[str] = None) -> Optional[str]:
    clean_caption = caption.strip() if caption else None
    if clean_caption and not is_url_only_text(clean_caption, source_url):
        return clean_caption
    return None


def draft_parse(shared_text: Optional[str], caption: Optional[str], source_url: str) -> dict[str, Any]:
    clean_caption = usable_caption_text(caption, source_url)
    clean_shared_text = usable_caption_text(shared_text, source_url)
    text = "\n".join(part for part in [clean_caption, clean_shared_text] if part)
    city, country = find_location(text)
    pinned = extract_pinned_place(text)
    if pinned and pinned[1] and not city:
        city = pinned[1]
    category = infer_category(text)
    place_name = likely_place_name(text, city, country)
    tags = extract_tags(text)
    has_location = bool(city or country)
    has_place = bool(place_name)
    needs_review = not (has_place and has_location)

    return {
        "caption": clean_caption or clean_shared_text,
        "category": category,
        "place_name": place_name,
        "city": city,
        "country": country,
        "summary": summarize(text or source_url),
        "tags_json": tags,
        "confidence": 0.75 if has_place and has_location else 0.45 if has_location else 0.25,
        "needs_review": needs_review,
        "needs_google_places_lookup": bool(has_place and has_location),
        "status": "needs_review" if needs_review else "parsed",
    }


def dream_title(city: Optional[str], country: Optional[str], region: Optional[str] = None) -> str:
    if country == "United States":
        if region:
            return region
        if city:
            return city
    if country:
        return country
    if city:
        return city
    if region:
        return region
    return "Unsorted Travel Ideas"


def dream_group_location(city: Optional[str], country: Optional[str], region: Optional[str] = None) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if country == "United States":
        return city, country, region
    if country:
        return None, country, None
    if city:
        return city, None, region
    return None, None, None


def get_or_create_dream(
    db: Session,
    user_id: int,
    city: Optional[str],
    country: Optional[str],
    region: Optional[str] = None,
) -> Dream:
    title = dream_title(city, country, region)
    dream = (
        db.query(Dream)
        .filter(
            Dream.user_id == user_id,
            Dream.title == title,
            Dream.city.is_(city) if city is None else Dream.city == city,
            Dream.country.is_(country) if country is None else Dream.country == country,
            Dream.region.is_(region) if region is None else Dream.region == region,
        )
        .first()
    )
    if dream:
        return dream

    dream = Dream(user_id=user_id, title=title, city=city, country=country, region=region)
    db.add(dream)
    db.flush()
    return dream


def dream_counts(db: Session, user_id: int) -> dict[int, dict[str, int]]:
    rows = (
        db.query(
            DreamItem.dream_id,
            func.count(DreamItem.id).label("item_count"),
            func.sum(case((DreamItem.needs_review.is_(True), 1), else_=0)).label("needs_review_count"),
            func.sum(case((DreamItem.status == "processing", 1), else_=0)).label("processing_count"),
        )
        .filter(DreamItem.user_id == user_id)
        .group_by(DreamItem.dream_id)
        .all()
    )
    return {
        row.dream_id: {
            "item_count": int(row.item_count or 0),
            "needs_review_count": int(row.needs_review_count or 0),
            "processing_count": int(row.processing_count or 0),
        }
        for row in rows
    }


def apply_parsed_item_to_dream_item(db: Session, item: DreamItem, parsed_item: Any, user_id: int) -> None:
    previous_dream_id = item.dream_id
    item.category = parsed_item.category
    item.place_name = parsed_item.place_name
    item.city = parsed_item.city
    item.country = parsed_item.country
    item.region_or_neighborhood = parsed_item.region_or_neighborhood
    item.summary = parsed_item.summary
    item.tags_json = parsed_item.tags
    item.confidence = parsed_item.confidence
    item.needs_review = parsed_item.needs_review
    item.needs_google_places_lookup = parsed_item.needs_google_places_lookup
    item.status = "needs_review" if parsed_item.needs_review else "parsed"
    item.updated_at = datetime.utcnow()

    dream_city, dream_country, dream_region = dream_group_location(
        parsed_item.city,
        parsed_item.country,
        parsed_item.region_or_neighborhood,
    )
    dream = get_or_create_dream(db, user_id, dream_city, dream_country, dream_region)
    item.dream_id = dream.id
    if previous_dream_id != dream.id:
        delete_empty_dream(db, previous_dream_id, user_id)


def delete_empty_dream(db: Session, dream_id: Optional[int], user_id: int) -> None:
    if not dream_id:
        return
    has_items = db.query(DreamItem.id).filter(DreamItem.dream_id == dream_id, DreamItem.user_id == user_id).first()
    if has_items:
        return
    dream = db.query(Dream).filter(Dream.id == dream_id, Dream.user_id == user_id).first()
    if dream:
        db.delete(dream)


def dream_item_coordinates(item: DreamItem) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Read saved location evidence without writes or provider requests."""
    return location_coordinates(item)


def dream_item_out(item: DreamItem) -> DreamItemOut:
    raw = item.raw_metadata_json or {}
    metadata = raw.get("instagram_metadata") if isinstance(raw, dict) else None
    thumbnail_url = f"/dream-items/{item.id}/thumbnail" if isinstance(metadata, dict) and metadata.get("thumbnail_url") else None
    latitude, longitude, coordinate_precision = dream_item_coordinates(item)
    location_fields = public_location(item)
    if location_fields.get("location_provider") == "google_places" and not google_map_capable.get():
        latitude = longitude = coordinate_precision = None
        location_fields["location_expires_at"] = None
    return DreamItemOut(
        id=item.id,
        dream_id=item.dream_id,
        source_platform=item.source_platform,
        source_url=item.source_url,
        caption=item.caption,
        category=item.category,
        place_name=item.place_name,
        city=item.city,
        country=item.country,
        region_or_neighborhood=item.region_or_neighborhood,
        summary=item.summary,
        tags_json=item.tags_json,
        confidence=item.confidence,
        needs_review=item.needs_review,
        needs_google_places_lookup=item.needs_google_places_lookup,
        google_place_id=item.google_place_id,
        google_maps_url=location_maps_url(item),
        **location_fields,
        thumbnail_url=thumbnail_url,
        latitude=latitude,
        longitude=longitude,
        coordinate_precision=coordinate_precision,
        status=item.status,
        processing_message=item.enrichment.message if item.enrichment else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/dream-items/{item_id}/thumbnail")
def get_dream_item_thumbnail(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = db.query(DreamItem).filter(DreamItem.id == item_id, DreamItem.user_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Dream item not found")

    cached = read_cached_thumbnail(item.id)
    if cached:
        content, content_type = cached
        return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=604800"})

    raw = item.raw_metadata_json or {}
    metadata = raw.get("instagram_metadata") if isinstance(raw, dict) else None
    thumbnail_url = metadata.get("thumbnail_url") if isinstance(metadata, dict) else None
    try:
        if not thumbnail_url:
            refreshed = fetch_instagram_metadata(item.source_url)
            metadata = refreshed.model_dump()
            thumbnail_url = refreshed.thumbnail_url
        if not thumbnail_url:
            raise DreamThumbnailError("Instagram metadata did not include a thumbnail")
        try:
            content, content_type = cache_thumbnail(item.id, thumbnail_url)
        except DreamThumbnailError:
            refreshed = fetch_instagram_metadata(item.source_url)
            metadata = refreshed.model_dump()
            if not refreshed.thumbnail_url:
                raise
            content, content_type = cache_thumbnail(item.id, refreshed.thumbnail_url)
    except (DreamThumbnailError, InstagramMetadataError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    item.raw_metadata_json = {**raw, "instagram_metadata": metadata}
    db.commit()
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=604800"})


def deterministic_caption_fallback(
    caption: str,
    source_url: str,
    *,
    error: str,
) -> DreamParseResponse:
    draft = draft_parse(None, caption, source_url)
    return DreamParseResponse(
        items=[
            DreamParseItem(
                category=draft["category"],
                place_name=draft["place_name"],
                city=draft["city"],
                country=draft["country"],
                summary=draft["summary"],
                tags=draft["tags_json"],
                confidence=draft["confidence"],
                needs_google_places_lookup=draft["needs_google_places_lookup"],
                needs_review=draft["needs_review"],
            )
        ],
        model="deterministic-caption-fallback",
        provider="deterministic",
        raw={"parser_error": error},
    )


def resolve_caption_for_parse(
    source_url: Optional[str],
    caption: Optional[str],
) -> tuple[str, dict[str, Any]]:
    clean_caption = usable_caption_text(caption, source_url)
    if clean_caption:
        return clean_caption, {}
    if not source_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="caption or source_url is required",
        )

    try:
        metadata = fetch_instagram_metadata(source_url)
    except InstagramMetadataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    resolved_caption = metadata.caption or metadata.title
    if not resolved_caption:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No caption text found for source_url",
        )
    return resolved_caption, metadata.model_dump()


@router.post("/parse-travel-caption", response_model=DreamParseResponse)
def parse_travel_caption(
    payload: ParseTravelCaptionRequest,
    current_user: User = Depends(get_current_user),
) -> DreamParseResponse:
    try:
        caption, _metadata = resolve_caption_for_parse(payload.source_url, payload.caption)
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_422_UNPROCESSABLE_ENTITY, status.HTTP_502_BAD_GATEWAY):
            return fallback_needs_review_response(
                payload.source_url or "Saved Instagram link",
                error=str(exc.detail),
            )
        raise
    try:
        return parse_caption_with_fallback_model(caption, payload.source_url)
    except DreamParserError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/parse-travel-caption/batch", response_model=ParseTravelCaptionBatchResponse)
def parse_travel_caption_batch(
    payload: ParseTravelCaptionBatchRequest,
    current_user: User = Depends(get_current_user),
) -> ParseTravelCaptionBatchResponse:
    urls = batch_source_urls(payload)
    results: list[ParseTravelCaptionBatchResult] = []

    for source_url in urls:
        try:
            caption, _metadata = resolve_caption_for_parse(source_url, None)
            parsed = parse_caption_with_fallback_model(caption, source_url)
            results.append(ParseTravelCaptionBatchResult(source_url=source_url, ok=True, result=parsed))
        except HTTPException as exc:
            if exc.status_code in (status.HTTP_422_UNPROCESSABLE_ENTITY, status.HTTP_502_BAD_GATEWAY):
                parsed = fallback_needs_review_response(source_url, error=str(exc.detail))
                results.append(ParseTravelCaptionBatchResult(source_url=source_url, ok=True, result=parsed))
                continue
            results.append(
                ParseTravelCaptionBatchResult(
                    source_url=source_url,
                    ok=False,
                    error=str(exc.detail),
                )
            )
        except (DreamParserError, HTTPException) as exc:
            error = exc.detail if isinstance(exc, HTTPException) else str(exc)
            results.append(
                ParseTravelCaptionBatchResult(
                    source_url=source_url,
                    ok=False,
                    error=str(error),
                )
            )

    succeeded = sum(1 for result in results if result.ok)
    return ParseTravelCaptionBatchResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


def capture_dream(db: Session, payload: ShareDreamRequest, user_id: int):
    source_url = normalize_source_url(payload.source_url)
    # Lock the owner before checking absent item/group rows. This serializes
    # simultaneous duplicate shares and grouping without a long provider call.
    db.query(User).filter(User.id == user_id).with_for_update(key_share=True).one()
    item = db.query(DreamItem).filter_by(user_id=user_id, source_url=source_url).with_for_update().first()
    if item:
        job = None
        if item.status in {"created", "processing", "needs_review", "failed"} and not (item.place_name or item.city or item.country):
            job, _ = enqueue_enrichment(db, item)
        return item, True, job
    parsed = draft_parse(payload.shared_text, payload.caption, source_url)
    dream_city, dream_country, dream_region = dream_group_location(parsed["city"], parsed["country"])
    dream = get_or_create_dream(db, user_id, dream_city, dream_country, dream_region)
    item = DreamItem(
        user_id=user_id, dream_id=dream.id, source_platform=payload.source_platform,
        source_url=source_url, caption=parsed["caption"], category=parsed["category"],
        place_name=parsed["place_name"], city=parsed["city"], country=parsed["country"],
        summary=parsed["summary"], tags_json=parsed["tags_json"], confidence=parsed["confidence"],
        needs_review=parsed["needs_review"], needs_google_places_lookup=parsed["needs_google_places_lookup"],
        status=parsed["status"], raw_metadata_json={"shared_text": payload.shared_text},
    )
    if item.place_name:
        item.google_maps_url = build_google_maps_search_url(item.place_name, item.city, item.country)
    db.add(item)
    db.flush()
    job, _ = enqueue_enrichment(db, item)
    return item, False, job


@router.post("/dreams/share", response_model=ShareDreamResponse)
def share_to_dreams(
    payload: ShareDreamRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShareDreamResponse:
    item, duplicate, job = capture_dream(db, payload, current_user.id)
    # Capture IDs before commit expiry so the wakeup cannot start a new transaction.
    job_id = job.id if job else None
    result = ShareDreamResponse(dream_item_id=item.id, dream_id=item.dream_id, status=item.status, duplicate=duplicate)
    db.commit()
    if job_id:
        background_tasks.add_task(notify_enrichment, [job_id])
    return result


@router.post("/dreams/import-instagram-batch", response_model=ImportInstagramBatchResponse)
def import_instagram_batch(
    payload: ImportInstagramBatchRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportInstagramBatchResponse:
    urls = batch_source_urls(ParseTravelCaptionBatchRequest(source_urls=payload.source_urls, links_text=payload.links_text))
    if len(urls) > 1000:
        raise HTTPException(status_code=422, detail="Import at most 1000 links at a time")
    results: list[ImportInstagramBatchResult] = []
    jobs = []
    for source_url in urls:
        item, duplicate, job = capture_dream(db, ShareDreamRequest(source_url=source_url), current_user.id)
        results.append(ImportInstagramBatchResult(
            source_url=source_url, dream_item_id=item.id, dream_id=item.dream_id,
            status=item.status, duplicate=duplicate, place_name=item.place_name, city=item.city,
            country=item.country, region=item.region_or_neighborhood,
            google_maps_url=item.google_maps_url, needs_review=item.needs_review,
            note="duplicate" if duplicate else None,
        ))
        if job:
            jobs.append(job.id)
        # Each captured URL survives a later item failure or request interruption.
        db.commit()
    if jobs:
        background_tasks.add_task(notify_enrichment, jobs)
    duplicate_count = sum(result.duplicate for result in results)
    return ImportInstagramBatchResponse(total=len(results), imported=len(results) - duplicate_count,
                                         duplicates=duplicate_count, results=results)


@router.post("/dreams/sort")
def sort_dreams(
    payload: SortDreamsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ids = sorted(set(payload.item_ids))
    items = db.query(DreamItem).filter(DreamItem.user_id == current_user.id, DreamItem.id.in_(ids)).order_by(
        DreamItem.id).with_for_update().all()
    if len(items) != len(ids):
        raise HTTPException(status_code=404, detail="Dream item not found")
    queued, jobs, processing_ids = 0, [], []
    for item in items:
        row, added = enqueue_enrichment(db, item, force=True)
        if row and row.status in {"queued", "running"}:
            jobs.append(row.id)
            processing_ids.append(item.id)
        queued += int(added)
    db.commit()
    if jobs:
        background_tasks.add_task(notify_enrichment, jobs)
    return {"queued": queued, "processing": len(processing_ids), "item_ids": processing_ids,
            "skipped": len(ids) - len(processing_ids)}


@router.get("/dreams", response_model=list[DreamOut])
def list_dreams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DreamOut]:
    counts = dream_counts(db, current_user.id)
    dreams = (
        db.query(Dream)
        .filter(Dream.user_id == current_user.id, Dream.id.in_(counts.keys()))
        .order_by(Dream.updated_at.desc())
        .all()
        if counts
        else []
    )
    return [
        DreamOut(
            id=dream.id,
            title=dream.title,
            country=dream.country,
            city=dream.city,
            region=dream.region,
            status=dream.status,
            created_at=dream.created_at,
            updated_at=dream.updated_at,
            **counts.get(dream.id, {"item_count": 0, "needs_review_count": 0, "processing_count": 0}),
        )
        for dream in dreams
    ]


@router.get("/dreams/{dream_id}/items", response_model=list[DreamItemOut])
def list_dream_items(
    dream_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DreamItemOut]:
    dream = db.query(Dream).filter(Dream.id == dream_id, Dream.user_id == current_user.id).first()
    if not dream:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dream not found")
    items = (
        db.query(DreamItem)
        .filter(DreamItem.dream_id == dream_id, DreamItem.user_id == current_user.id)
        .options(selectinload(DreamItem.enrichment), selectinload(DreamItem.location).selectinload(DreamLocation.google_identity))
        .order_by(DreamItem.created_at.desc())
        .all()
    )
    return [dream_item_out(item) for item in items]


@router.get("/dream-items", response_model=list[DreamItemOut])
def list_items(
    item_status: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DreamItemOut]:
    query = db.query(DreamItem).options(selectinload(DreamItem.enrichment), selectinload(DreamItem.location).selectinload(DreamLocation.google_identity)).filter(DreamItem.user_id == current_user.id)
    if item_status:
        if item_status == "needs_review":
            query = query.filter(DreamItem.needs_review.is_(True))
        else:
            query = query.filter(DreamItem.status == item_status)
    return [dream_item_out(item) for item in query.order_by(DreamItem.created_at.desc()).all()]


@router.post("/dream-items/{item_id}/parse", response_model=DreamItemOut)
def parse_item(
    item_id: int,
    background_tasks: BackgroundTasks,
    payload: ParseDreamItemRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DreamItemOut:
    item = db.query(DreamItem).filter(DreamItem.id == item_id, DreamItem.user_id == current_user.id).with_for_update().first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dream item not found")
    # Confirmed or manually edited saves retain all of the user's choices.
    if item.status != "confirmed" and not (item.raw_metadata_json or {}).get("dream_user_edited"):
        if payload and payload.caption:
            item.caption = payload.caption
        row, _ = enqueue_enrichment(db, item, force=True)
        job_id = row.id if row else None
    else:
        job_id = None
    result = dream_item_out(item)
    db.commit()
    if job_id:
        background_tasks.add_task(notify_enrichment, [job_id])
    return result


@router.post("/dream-items/{item_id}/review", response_model=DreamItemOut)
def review_item(
    item_id: int,
    payload: ReviewDreamItemRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DreamItemOut:
    item = db.query(DreamItem).filter(DreamItem.id == item_id, DreamItem.user_id == current_user.id).with_for_update().first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dream item not found")

    cancel_enrichment(db, item, user_edited=True)

    if payload.edits:
        edits = payload.edits.model_dump(exclude_unset=True)
        identity_changed = any(
            field in edits and str(edits[field] or "").strip().casefold() != str(getattr(item, field) or "").strip().casefold()
            for field in ("place_name", "city", "country", "region_or_neighborhood", "category")
        )
        maps_changed = "google_maps_url" in edits and edits["google_maps_url"] != item.google_maps_url
        from ..services.dream_locations import explicit_pin
        had_manual_pin = explicit_pin(item)[0] is not None
        place_identity_changed = any(
            field in edits and str(edits[field] or "").strip().casefold() != str(getattr(item, field) or "").strip().casefold()
            for field in ("place_name", "city", "country", "region_or_neighborhood")
        )
        preserve_google_category_choice = bool(item.location and item.location.provider == "google_places"
            and item.location.google_identity and item.location.google_identity.confirmed_place_id
            and not place_identity_changed and not maps_changed)
        if (identity_changed or maps_changed) and not preserve_google_category_choice:
            raw = dict(item.raw_metadata_json or {})
            previous = raw.pop("place_match", None)
            if previous or item.google_maps_url or item.google_place_id:
                history = raw.get("previous_place_matches")
                google_content = isinstance(previous, dict) and isinstance(previous.get("raw"), dict) and isinstance(previous["raw"].get("location"), dict)
                raw["previous_place_matches"] = [*(history if isinstance(history, list) else []), {
                    "place_match": None if google_content else previous, "google_maps_url": None if google_content else item.google_maps_url,
                    "google_place_id": item.google_place_id, "replaced_at": datetime.utcnow().isoformat(),
                }]
            item.raw_metadata_json = raw
            if "google_place_id" not in edits:
                item.google_place_id = None
            if identity_changed and not maps_changed and not had_manual_pin:
                edits["google_maps_url"] = None
        dream_id = edits.pop("dream_id", None)
        if dream_id is not None:
            dream = db.query(Dream).filter(Dream.id == dream_id, Dream.user_id == current_user.id).first()
            if not dream:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dream not found")
            item.dream_id = dream.id
        for field, value in edits.items():
            setattr(item, field, value)
        if dream_id is None and ("city" in edits or "country" in edits or "region_or_neighborhood" in edits):
            dream = get_or_create_dream(
                db,
                current_user.id,
                item.city,
                item.country,
                item.region_or_neighborhood,
            )
            item.dream_id = dream.id

    if payload.decision == "confirm":
        item.needs_review = False
        item.status = "confirmed"
        if item.place_name and (item.city or item.country):
            item.needs_google_places_lookup = item.google_place_id is None
    else:
        item.needs_review = True
        item.status = "needs_review"

    enqueue_location(db, item)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return dream_item_out(item)


@router.delete(
    "/dream-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    item = db.query(DreamItem).filter(DreamItem.id == item_id, DreamItem.user_id == current_user.id).with_for_update().first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dream item not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/dream-items/{item_id}/locate", response_model=DreamItemOut)
def locate_item(item_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.query(DreamItem).filter_by(id=item_id, user_id=current_user.id).with_for_update().first()
    if not item:
        raise HTTPException(status_code=404, detail="Dream item not found")
    enqueue_location(db, item, force=True)
    db.commit()
    db.refresh(item)
    return dream_item_out(item)


@router.get("/dream-items/{item_id}/location-details")
async def get_item_location_details(item_id: int, response: Response,
                                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..services.google_location_lifecycle import live_google_details
    from ..services.dream_place_search import RetryableDreamPlaceLookupError
    response.headers["Cache-Control"] = "private, no-store"
    if not db.query(DreamItem.id).filter_by(id=item_id, user_id=current_user.id).first():
        raise HTTPException(status_code=404, detail="Dream item not found")
    if not google_map_capable.get():
        raise HTTPException(status_code=409, detail="Google Maps support is required to display these place details.",
                            headers={"Cache-Control": "private, no-store"})
    try:
        return await live_google_details(db, item_id, current_user.id)
    except RetryableDreamPlaceLookupError:
        raise HTTPException(status_code=503, detail="Place details are temporarily unavailable. Try again.",
                            headers={"Cache-Control": "private, no-store"})
    except LookupError:
        raise HTTPException(status_code=404, detail="Dream item not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/dream-items/{item_id}/location-confirm", response_model=DreamItemOut)
async def confirm_item_location(item_id: int, payload: ConfirmLocationRequest,
                          current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.query(DreamItem).filter_by(id=item_id, user_id=current_user.id).with_for_update().first()
    if not item:
        raise HTTPException(status_code=404, detail="Dream item not found")
    try:
        if item.location and item.location.provider == "google_places":
            from ..services.google_location_lifecycle import confirm_google_candidate
            from ..services.google_dream_place_search import GooglePlacesBlockedError
            from ..services.dream_place_search import RetryableDreamPlaceLookupError
            try:
                item = await confirm_google_candidate(db, item_id, current_user.id, payload.candidate_id)
            except (GooglePlacesBlockedError, RetryableDreamPlaceLookupError):
                db.rollback()
                raise HTTPException(status_code=503, detail="Place details are temporarily unavailable. Try again.")
        else:
            confirm_candidate(db, item, payload.candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError:
        raise HTTPException(status_code=404, detail="Dream item not found")
    cancel_enrichment(db, item, user_edited=True)
    db.commit()
    db.refresh(item)
    return dream_item_out(item)


@router.post("/dreams/locate-missing")
def locate_missing_items(payload: LocateMissingRequest | None = None,
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(DreamItem).filter_by(user_id=current_user.id)
    requested = set(payload.item_ids) if payload and payload.item_ids is not None else None
    if requested is not None:
        query = query.filter(DreamItem.id.in_(requested))
    items = query.order_by(DreamItem.id).with_for_update().all()
    if requested is not None and len(items) != len(requested):
        raise HTTPException(status_code=404, detail="Dream item not found")
    queued = 0
    for item in items:
        if (item.place_name or "").strip() and location_coordinates(item)[0] is None:
            _, added = enqueue_location(db, item, force=True)
            queued += int(added)
    db.commit()
    return {"queued": queued, "items": [dream_item_out(item) for item in items]}
