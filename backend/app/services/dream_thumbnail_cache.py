"""Local cache for short-lived Instagram Dream thumbnails."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from .instagram_metadata import DEFAULT_USER_AGENT

MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024


class DreamThumbnailError(RuntimeError):
    pass


def thumbnail_cache_dir() -> Path:
    configured = os.getenv("DREAM_THUMBNAIL_CACHE_DIR")
    root = Path(configured) if configured else Path(__file__).resolve().parents[2] / ".cache" / "dream-thumbnails"
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_cached_thumbnail(item_id: int) -> tuple[bytes, str] | None:
    root = thumbnail_cache_dir()
    image_path = root / f"{item_id}.bin"
    metadata_path = root / f"{item_id}.json"
    if not image_path.exists():
        return None
    try:
        content = image_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return None
    if not content:
        return None
    return content, str(metadata.get("content_type") or "image/jpeg")


def cache_thumbnail(item_id: int, thumbnail_url: str, *, timeout_seconds: float = 15) -> tuple[bytes, str]:
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": "https://www.instagram.com/",
        "User-Agent": os.getenv("INSTAGRAM_METADATA_USER_AGENT", DEFAULT_USER_AGENT),
    }
    try:
        response = httpx.get(thumbnail_url, headers=headers, follow_redirects=True, timeout=timeout_seconds)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DreamThumbnailError(f"Instagram thumbnail fetch failed: {exc}") from exc

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    content = response.content
    if not content_type.startswith("image/"):
        raise DreamThumbnailError(f"Instagram thumbnail returned {content_type or 'non-image content'}")
    if not content or len(content) > MAX_THUMBNAIL_BYTES:
        raise DreamThumbnailError("Instagram thumbnail was empty or too large")

    root = thumbnail_cache_dir()
    (root / f"{item_id}.bin").write_bytes(content)
    (root / f"{item_id}.json").write_text(
        json.dumps({"content_type": content_type, "source_url": thumbnail_url}, indent=2),
        encoding="utf-8",
    )
    return content, content_type
