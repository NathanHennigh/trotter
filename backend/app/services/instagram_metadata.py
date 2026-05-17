"""Best-effort metadata fetching for Instagram share URLs."""

from __future__ import annotations

import html
import os
import re
from typing import Optional
from urllib.parse import quote, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class InstagramMetadata(BaseModel):
    source_url: str
    caption: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    fetched: bool = False
    error: Optional[str] = None


class InstagramMetadataError(RuntimeError):
    pass


def canonical_instagram_url(source_url: str) -> str:
    parsed = urlparse(source_url if "://" in source_url else f"https://{source_url}")
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunparse(("https", netloc, path, "", "", ""))


def oembed_instagram_url(source_url: str) -> str:
    canonical = canonical_instagram_url(source_url)
    parsed = urlparse(canonical)
    path = parsed.path.rstrip("/") + "/"
    return urlunparse(("https", "www.instagram.com", path, "", "", ""))


def _clean_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\d+[KMB]?\s+likes,\s*\d+[KMB]?\s+comments\s*-\s*", "", text, flags=re.I)
    text = re.sub(r"^.*?\son Instagram:\s*", "", text, flags=re.I)
    text = text.strip(" -")
    return text or None


def _meta_content(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"])
    return None


def extract_instagram_metadata_from_html(source_url: str, html_text: str) -> InstagramMetadata:
    soup = BeautifulSoup(html_text, "html.parser")
    raw_title = _meta_content(soup, "og:title", "twitter:title")
    raw_description = _meta_content(soup, "og:description", "description", "twitter:description")
    thumbnail_url = _meta_content(soup, "og:image", "twitter:image")

    title = _clean_text(raw_title)
    description = _clean_text(raw_description)
    caption = description

    if caption and title and caption == title:
        title = None

    return InstagramMetadata(
        source_url=source_url,
        caption=caption,
        title=title,
        description=description,
        thumbnail_url=thumbnail_url,
        fetched=bool(caption or title or thumbnail_url),
    )


def fetch_instagram_metadata(
    source_url: str,
    *,
    timeout_seconds: Optional[float] = None,
) -> InstagramMetadata:
    source_url = canonical_instagram_url(source_url)
    timeout = timeout_seconds or float(os.getenv("INSTAGRAM_METADATA_TIMEOUT_SECONDS", "12"))
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": os.getenv("INSTAGRAM_METADATA_USER_AGENT", DEFAULT_USER_AGENT),
    }
    try:
        response = httpx.get(source_url, headers=headers, follow_redirects=True, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise InstagramMetadataError(f"Instagram metadata fetch failed: {exc}") from exc

    metadata = extract_instagram_metadata_from_html(str(response.url), response.text)
    if metadata.caption or metadata.title:
        return metadata

    return fetch_instagram_oembed_metadata(source_url, timeout_seconds=timeout)


def fetch_instagram_oembed_metadata(
    source_url: str,
    *,
    timeout_seconds: Optional[float] = None,
) -> InstagramMetadata:
    source_url = canonical_instagram_url(source_url)
    timeout = timeout_seconds or float(os.getenv("INSTAGRAM_METADATA_TIMEOUT_SECONDS", "12"))
    embed_source_url = oembed_instagram_url(source_url)
    oembed_url = f"https://www.instagram.com/api/v1/oembed/?url={quote(embed_source_url, safe='')}"
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": os.getenv("INSTAGRAM_METADATA_USER_AGENT", DEFAULT_USER_AGENT),
    }
    try:
        response = httpx.get(oembed_url, headers=headers, follow_redirects=True, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise InstagramMetadataError(f"Instagram oEmbed metadata fetch failed: {exc}") from exc

    body = response.json()
    title = _clean_text(body.get("title"))
    if not title:
        raise InstagramMetadataError("Instagram metadata did not include parseable caption text")

    return InstagramMetadata(
        source_url=source_url,
        caption=title,
        title=title,
        description=title,
        thumbnail_url=body.get("thumbnail_url"),
        fetched=True,
    )
