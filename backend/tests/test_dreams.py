"""Tests for Dreams share capture and review endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Dream, DreamItem, User
from app.routers.auth import get_current_user
from app.services.dream_parser import DreamParseItem, DreamParseResponse


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Dream.__table__.create(engine)
    DreamItem.__table__.create(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    session = Session()
    yield session
    session.close()
    app.dependency_overrides.pop(get_db, None)
    DreamItem.__table__.drop(engine)
    Dream.__table__.drop(engine)
    User.__table__.drop(engine)


@pytest.fixture
def test_user(test_db):
    user = User(id=1, email="test@example.com", name="Test User")
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)

    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def default_dream_enrichment_mocks(monkeypatch):
    def fake_parse(caption, source_url=None):
        if "Casa Dani" in caption or "Madrid" in caption:
            return DreamParseResponse(
                items=[
                    DreamParseItem(
                        category="restaurant",
                        place_name="Casa Dani",
                        city="Madrid",
                        country="Spain",
                        summary="Tortilla spot in Madrid.",
                        tags=["food"],
                        confidence=0.94,
                        needs_google_places_lookup=True,
                        needs_review=False,
                    )
                ],
                model="qwen3.5:4b",
            )
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="unknown",
                    summary=caption or "Saved Instagram link",
                    confidence=0.0,
                    needs_review=True,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.parse_caption_with_fallback_model", fake_parse)
    monkeypatch.setattr("app.routers.dreams.search_geoapify_place", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.routers.dreams.search_google_place", lambda *args, **kwargs: None)


def test_share_requires_auth():
    app.dependency_overrides.pop(get_current_user, None)
    c = TestClient(app, raise_server_exceptions=False)
    response = c.post("/dreams/share", json={"source_url": "https://instagram.com/reel/test"})
    assert response.status_code in (401, 403)


def test_share_creates_unsorted_review_item(client, test_user, test_db):
    response = client.post(
        "/dreams/share",
        json={
            "source_platform": "instagram",
            "source_url": "https://www.instagram.com/reel/abc123/?utm_source=ig_web_copy_link",
            "shared_text": "This is your sign to book the trip.",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["duplicate"] is False
    assert data["status"] == "needs_review"

    item = test_db.query(DreamItem).filter(DreamItem.id == data["dream_item_id"]).one()
    assert item.source_url == "https://instagram.com/reel/abc123"
    assert item.needs_review is True
    assert item.dream.title == "Unsorted Travel Ideas"


def test_share_groups_obvious_caption_and_dedupes(client, test_user, test_db):
    payload = {
        "source_platform": "instagram",
        "source_url": "https://instagram.com/reel/madrid-food/",
        "shared_text": "Casa Dani\nBest tortilla in Madrid, Spain. #Madrid #Food",
    }

    first = client.post("/dreams/share", json=payload)
    second = client.post("/dreams/share", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert test_db.query(DreamItem).count() == 1

    item = test_db.query(DreamItem).one()
    assert item.place_name == "Casa Dani"
    assert item.city == "Madrid"
    assert item.country == "Spain"
    assert item.dream.title == "Spain"
    assert item.google_maps_url == "https://www.google.com/maps/search/?api=1&query=Casa+Dani+Madrid+Spain"


def test_list_dreams_includes_counts(client, test_user):
    client.post(
        "/dreams/share",
        json={"source_url": "https://instagram.com/reel/one", "shared_text": "A vague Europe idea"},
    )

    response = client.get("/dreams")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Unsorted Travel Ideas"
    assert data[0]["item_count"] == 1
    assert data[0]["needs_review_count"] == 1


def test_dream_thumbnail_uses_stable_authenticated_endpoint(client, test_user, test_db, monkeypatch):
    dream = Dream(user_id=test_user.id, title="Spain", country="Spain", status="active")
    test_db.add(dream)
    test_db.flush()
    item = DreamItem(
        user_id=test_user.id,
        dream_id=dream.id,
        source_platform="instagram",
        source_url="https://instagram.com/reel/thumb",
        category="attraction",
        summary="A saved place.",
        needs_review=False,
        needs_google_places_lookup=False,
        status="parsed",
        raw_metadata_json={"instagram_metadata": {"thumbnail_url": "https://instagram.example/expiring.jpg"}},
    )
    test_db.add(item)
    test_db.commit()
    test_db.refresh(item)

    monkeypatch.setattr("app.routers.dreams.read_cached_thumbnail", lambda item_id: (b"jpeg-data", "image/jpeg"))

    listed = client.get(f"/dreams/{dream.id}/items")
    assert listed.status_code == 200
    assert listed.json()[0]["thumbnail_url"] == f"/dream-items/{item.id}/thumbnail"

    thumbnail = client.get(f"/dream-items/{item.id}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"
    assert thumbnail.content == b"jpeg-data"


def test_review_confirm_applies_edits(client, test_user, test_db):
    created = client.post(
        "/dreams/share",
        json={"source_url": "https://instagram.com/reel/edit-me", "shared_text": "A vague food idea"},
    ).json()

    response = client.post(
        f"/dream-items/{created['dream_item_id']}/review",
        json={
            "decision": "confirm",
            "edits": {
                "place_name": "Casa Dani",
                "city": "Madrid",
                "country": "Spain",
                "category": "restaurant",
                "summary": "Tortilla spot in Madrid.",
                "tags_json": ["food", "madrid"],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["needs_review"] is False
    assert data["place_name"] == "Casa Dani"
    assert data["dream_id"] != created["dream_id"]
    assert data["needs_google_places_lookup"] is True

    item = test_db.query(DreamItem).filter(DreamItem.id == created["dream_item_id"]).one()
    assert item.status == "confirmed"
    assert item.dream.title == "Spain"


def test_parse_caption_endpoint_uses_ollama_service(client, test_user, monkeypatch):
    def fake_parse(caption, source_url=None):
        assert "Casa Dani" in caption
        assert source_url == "https://instagram.com/reel/parser"
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="restaurant",
                    place_name="Casa Dani",
                    city="Madrid",
                    country="Spain",
                    summary="Tortilla spot in Madrid.",
                    tags=["food"],
                    confidence=0.94,
                    needs_google_places_lookup=True,
                    needs_review=False,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.parse_caption_with_fallback_model", fake_parse)

    response = client.post(
        "/parse-travel-caption",
        json={
            "source_url": "https://instagram.com/reel/parser",
            "caption": "Casa Dani\nBest tortilla in Madrid, Spain.",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "qwen3.5:4b"
    assert data["items"][0]["place_name"] == "Casa Dani"


def test_parse_caption_endpoint_can_fetch_caption_from_url(client, test_user, monkeypatch):
    def fake_metadata(source_url):
        class Metadata:
            caption = "Casa Dani in Madrid, Spain. Best tortilla."
            title = None

            def model_dump(self):
                return {"caption": self.caption, "title": self.title, "source_url": source_url}

        return Metadata()

    def fake_parse(caption, source_url=None):
        assert caption == "Casa Dani in Madrid, Spain. Best tortilla."
        assert source_url == "https://instagram.com/reel/url-only"
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="restaurant",
                    place_name="Casa Dani",
                    city="Madrid",
                    country="Spain",
                    summary="Tortilla spot in Madrid.",
                    tags=["food"],
                    confidence=0.94,
                    needs_google_places_lookup=True,
                    needs_review=False,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_fallback_model", fake_parse)

    response = client.post(
        "/parse-travel-caption",
        json={"source_url": "https://instagram.com/reel/url-only"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["city"] == "Madrid"


def test_parse_caption_endpoint_returns_review_item_when_metadata_missing(client, test_user, monkeypatch):
    from app.services.instagram_metadata import InstagramMetadataError

    def fake_metadata(source_url):
        raise InstagramMetadataError("Instagram metadata did not include parseable caption text")

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)

    response = client.post(
        "/parse-travel-caption",
        json={"source_url": "https://instagram.com/reel/no-caption"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["needs_review"] is True
    assert data["items"][0]["confidence"] == 0.0
    assert "metadata" in data["raw"]["parser_error"]


def test_parse_caption_batch_accepts_url_array_and_keeps_failures(client, test_user, monkeypatch):
    def fake_metadata(source_url):
        if "blocked" in source_url:
            from app.services.instagram_metadata import InstagramMetadataError

            raise InstagramMetadataError("Instagram metadata fetch failed: blocked")

        class Metadata:
            caption = "Casa Dani in Madrid, Spain. Best tortilla."
            title = None

            def model_dump(self):
                return {"caption": self.caption, "title": self.title, "source_url": source_url}

        return Metadata()

    def fake_parse(caption, source_url=None):
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="restaurant",
                    place_name="Casa Dani",
                    city="Madrid",
                    country="Spain",
                    summary="Tortilla spot in Madrid.",
                    tags=["food"],
                    confidence=0.94,
                    needs_google_places_lookup=True,
                    needs_review=False,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_ollama", fake_parse)

    response = client.post(
        "/parse-travel-caption/batch",
        json={
            "source_urls": [
                "https://www.instagram.com/reel/good/",
                "https://www.instagram.com/reel/blocked/",
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    assert data["results"][0]["ok"] is True
    assert data["results"][1]["ok"] is True
    assert data["results"][1]["result"]["items"][0]["needs_review"] is True
    assert "blocked" in data["results"][1]["result"]["raw"]["parser_error"]


def test_parse_caption_batch_accepts_pasted_links_and_dedupes(client, test_user, monkeypatch):
    seen_urls = []

    def fake_metadata(source_url):
        seen_urls.append(source_url)

        class Metadata:
            caption = "Lisbon cafe list"
            title = None

            def model_dump(self):
                return {"caption": self.caption, "title": self.title, "source_url": source_url}

        return Metadata()

    def fake_parse(caption, source_url=None):
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="cafe",
                    place_name=None,
                    city="Lisbon",
                    country="Portugal",
                    summary="Lisbon cafe list.",
                    tags=[],
                    confidence=0.65,
                    needs_google_places_lookup=False,
                    needs_review=True,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_ollama", fake_parse)

    response = client.post(
        "/parse-travel-caption/batch",
        json={
            "links_text": """
            https://www.instagram.com/reel/one/
            random text https://instagram.com/reel/two/.
            duplicate: https://www.instagram.com/reel/one/
            """
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert seen_urls == ["https://instagram.com/reel/one", "https://instagram.com/reel/two"]


def test_parse_item_applies_parser_result_and_regroups(client, test_user, test_db, monkeypatch):
    created = client.post(
        "/dreams/share",
        json={
            "source_url": "https://instagram.com/reel/parse-item",
            "shared_text": "Saving this for later",
        },
    ).json()

    def fake_parse(caption, source_url=None):
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="restaurant",
                    place_name="Casa Dani",
                    city="Madrid",
                    country="Spain",
                    summary="Tortilla spot in Madrid.",
                    tags=["food", "madrid"],
                    confidence=0.94,
                    needs_google_places_lookup=True,
                    needs_review=False,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.parse_caption_with_ollama", fake_parse)

    response = client.post(
        f"/dream-items/{created['dream_item_id']}/parse",
        json={"caption": "Casa Dani\nBest tortilla in Madrid, Spain."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "parsed"
    assert data["needs_review"] is False
    assert data["place_name"] == "Casa Dani"
    assert data["dream_id"] != created["dream_id"]

    item = test_db.query(DreamItem).filter(DreamItem.id == created["dream_item_id"]).one()
    assert item.dream.title == "Spain"
    assert item.raw_metadata_json["parser_model"] == "qwen3.5:4b"


def test_parse_item_without_caption_fetches_metadata(client, test_user, test_db, monkeypatch):
    created = client.post(
        "/dreams/share",
        json={"source_url": "https://instagram.com/reel/url-metadata"},
    ).json()

    def fake_metadata(source_url):
        class Metadata:
            caption = "Casa Dani in Madrid, Spain. Best tortilla."
            title = None

            def model_dump(self):
                return {"caption": self.caption, "title": self.title, "source_url": source_url}

        return Metadata()

    def fake_parse(caption, source_url=None):
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="restaurant",
                    place_name="Casa Dani",
                    city="Madrid",
                    country="Spain",
                    summary="Tortilla spot in Madrid.",
                    tags=["food"],
                    confidence=0.94,
                    needs_google_places_lookup=True,
                    needs_review=False,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_ollama", fake_parse)

    response = client.post(f"/dream-items/{created['dream_item_id']}/parse")

    assert response.status_code == 200
    item = test_db.query(DreamItem).filter(DreamItem.id == created["dream_item_id"]).one()
    assert item.caption == "Casa Dani in Madrid, Spain. Best tortilla."
    assert item.raw_metadata_json["instagram_metadata"]["caption"] == item.caption


def test_duplicate_url_enrichment_uses_caption_fallback_when_model_is_down(client, test_user, test_db, monkeypatch):
    caption = (
        "Save this for your Thailand trip 🇹🇭 "
        "📍 Kuan Nom Saow Cafe, Krabi tag the person you'd go here with "
        "#krabithailand #thailand"
    )

    created = client.post(
        "/dreams/share",
        json={
            "source_url": "https://instagram.com/reel/thailand-cafe",
            "shared_text": "https://www.instagram.com/reel/thailand-cafe/",
        },
    ).json()

    def fake_metadata(source_url):
        metadata_caption = caption

        class Metadata:
            title = metadata_caption
            description = metadata_caption
            thumbnail_url = "https://example.com/thumb.jpg"
            fetched = True
            error = None

            @property
            def caption(self):
                return metadata_caption

            def model_dump(self):
                return {
                    "source_url": source_url,
                    "caption": self.caption,
                    "title": self.title,
                    "description": self.description,
                    "thumbnail_url": self.thumbnail_url,
                    "fetched": self.fetched,
                    "error": self.error,
                }

        return Metadata()

    def failed_parse(*args, **kwargs):
        from app.services.dream_parser import DreamParserError

        raise DreamParserError("Ollama unavailable")

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_fallback_model", failed_parse)

    response = client.post(
        "/dreams/share",
        json={"source_url": "https://instagram.com/reel/thailand-cafe"},
    )

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    item = test_db.query(DreamItem).filter(DreamItem.id == created["dream_item_id"]).one()
    assert item.place_name == "Kuan Nom Saow Cafe"
    assert item.city == "Krabi"
    assert item.country == "Thailand"
    assert item.category == "cafe"
    assert item.dream.title == "Thailand"


def test_delete_item_removes_user_owned_item(client, test_user, test_db):
    created = client.post(
        "/dreams/share",
        json={"source_url": "https://instagram.com/reel/delete-me", "shared_text": "delete"},
    ).json()

    response = client.delete(f"/dream-items/{created['dream_item_id']}")

    assert response.status_code == 204
    assert test_db.query(DreamItem).count() == 0


def test_import_instagram_batch_creates_dream_items_and_groups_foreign_by_country(client, test_user, test_db, monkeypatch):
    def fake_metadata(source_url):
        class Metadata:
            caption = "Casa Toro in Puerto Escondido, Mexico."
            title = None

            def model_dump(self):
                return {"caption": self.caption, "title": self.title, "source_url": source_url}

        return Metadata()

    def fake_parse(caption, source_url=None):
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="restaurant",
                    place_name="Casa Toro",
                    city="Puerto Escondido",
                    country="Mexico",
                    summary="Restaurant in Puerto Escondido.",
                    tags=["food"],
                    confidence=0.95,
                    needs_google_places_lookup=True,
                    needs_review=False,
                )
            ],
            model="qwen3.5:4b",
        )

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_fallback_model", fake_parse)
    monkeypatch.setattr("app.routers.dreams.search_google_place", lambda *args, **kwargs: None)

    response = client.post(
        "/dreams/import-instagram-batch",
        json={"source_urls": ["https://instagram.com/reel/casa-toro"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 1
    item = test_db.query(DreamItem).one()
    assert item.place_name == "Casa Toro"
    assert item.dream.title == "Mexico"
    assert item.city == "Puerto Escondido"


def test_import_instagram_batch_groups_us_by_region_and_attaches_maps(client, test_user, test_db, monkeypatch):
    def fake_metadata(source_url):
        class Metadata:
            caption = "Onera in Wimberley, United States."
            title = None

            def model_dump(self):
                return {"caption": self.caption, "title": self.title, "source_url": source_url}

        return Metadata()

    def fake_parse(caption, source_url=None):
        return DreamParseResponse(
            items=[
                DreamParseItem(
                    category="hotel",
                    place_name="Onera",
                    city="Wimberley",
                    country="United States",
                    summary="Cabin stay in Wimberley.",
                    tags=["stay"],
                    confidence=0.9,
                    needs_google_places_lookup=True,
                    needs_review=False,
                )
            ],
            model="qwen3.5:4b",
        )

    class Match:
        place_id = "places/onera"
        google_maps_url = "https://maps.google.com/?cid=onera"
        city = "Wimberley"
        region = "Texas"
        country = "United States"

        def model_dump(self):
            return {
                "place_id": self.place_id,
                "google_maps_url": self.google_maps_url,
                "city": self.city,
                "region": self.region,
                "country": self.country,
            }

    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", fake_metadata)
    monkeypatch.setattr("app.routers.dreams.parse_caption_with_fallback_model", fake_parse)
    monkeypatch.setattr("app.routers.dreams.search_google_place", lambda *args, **kwargs: Match())

    response = client.post(
        "/dreams/import-instagram-batch",
        json={"source_urls": ["https://instagram.com/p/onera"]},
    )

    assert response.status_code == 200
    item = test_db.query(DreamItem).one()
    assert item.google_maps_url == "https://maps.google.com/?cid=onera"
    assert item.region_or_neighborhood == "Texas"
    assert item.dream.title == "Texas"
