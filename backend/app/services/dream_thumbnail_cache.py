"""Local cache for short-lived Instagram Dream thumbnails."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from .instagram_metadata import DEFAULT_USER_AGENT

MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024
MAX_THUMBNAIL_PIXELS = 24_000_000
THUMBNAIL_WIDTHS = (240, 960)


def _write_atomically(path: Path, content: bytes) -> None:
    # Requests for the same post can arrive together from different screens or
    # workers. Never expose a partially written rendition to the next reader.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


class DreamThumbnailError(RuntimeError):
    pass


def thumbnail_item_id(item) -> int:
    """A post has one cover, even when it produces several saved places.

    Thumbnail endpoints eager-load this relationship. Reuse one rendition cache
    across place ordering and never borrow another owner's cached image.
    """
    siblings = item.source_post.items if item.source_post else [item]
    return min((row.id for row in siblings if row.user_id == item.user_id), default=item.id)


def thumbnail_variant(item_id: int, content: bytes, content_type: str, width: int | None) -> tuple[bytes, str]:
    """Bound transfer and decode size; the old endpoint still returns its original.

    Cache by input digest as well as size so a refreshed Instagram cover cannot
    silently reuse an earlier rendition. Unsupported formats keep the original.
    """
    if width not in THUMBNAIL_WIDTHS:
        return content, content_type
    digest = hashlib.sha256(content).hexdigest()[:20]
    path = thumbnail_cache_dir() / f"{item_id}-{digest}-v1-w{width}.webp"
    try:
        if path.is_file():
            return path.read_bytes(), "image/webp"
        with Image.open(io.BytesIO(content)) as original:
            if original.width * original.height > MAX_THUMBNAIL_PIXELS:
                raise DreamThumbnailError("Instagram thumbnail dimensions are too large")
            image = ImageOps.exif_transpose(original)
            # Reel covers are commonly portrait. Bound their width to the
            # requested display size while retaining enough pixels for a crop.
            image.thumbnail((width, width * 2), Image.Resampling.LANCZOS)
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = io.BytesIO()
            image.save(output, "WEBP", quality=78, method=4)
        resized = output.getvalue()
        # A tiny source can already be more efficient than a new encoding.
        if len(resized) >= len(content) and original.width <= width and original.height <= width * 2:
            return content, content_type
        _write_atomically(path, resized)
        return resized, "image/webp"
    except (UnidentifiedImageError, OSError, ValueError):
        return content, content_type
    except Image.DecompressionBombError as exc:
        raise DreamThumbnailError("Instagram thumbnail dimensions are too large") from exc


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
    _write_atomically(root / f"{item_id}.json", json.dumps({"content_type": content_type, "source_url": thumbnail_url}).encode("utf-8"))
    _write_atomically(root / f"{item_id}.bin", content)
    return content, content_type
