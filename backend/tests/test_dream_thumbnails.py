"""Cover transfer size, shared-source caching and ownership boundaries."""
from io import BytesIO

import pytest
from PIL import Image

from app.models import Dream, DreamItem, DreamSourcePost, User
from app.services import dream_thumbnail_cache as cache
from test_dreams import client, test_db, test_user


@pytest.fixture(autouse=True)
def isolated_images(monkeypatch, tmp_path):
    monkeypatch.setenv("DREAM_THUMBNAIL_CACHE_DIR", str(tmp_path))


def jpeg(size=(1600, 2400), color="#8b9ca4"):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, "JPEG", quality=92)
    return output.getvalue()


def saved_places(test_db, test_user):
    dream = Dream(user_id=test_user.id, title="Morocco", country="Morocco", status="active")
    source = DreamSourcePost(user_id=test_user.id, source_url="https://instagram.com/reel/one-cover", source_platform="instagram")
    test_db.add_all([dream, source])
    test_db.flush()
    rows = [DreamItem(user_id=test_user.id, dream_id=dream.id, source_post_id=source.id,
                      source_url=source.source_url, source_platform="instagram", source_place_key=str(index),
                      category="attraction", summary="Saved place", needs_review=False,
                      needs_google_places_lookup=False, status="parsed",
                      raw_metadata_json={"instagram_metadata": {"thumbnail_url": "https://cdn.test/cover.jpg"}})
            for index in range(3)]
    test_db.add_all(rows)
    test_db.commit()
    return dream, rows


def test_thumbnail_renditions_bound_pixels_and_transfer_and_reuse_cache(monkeypatch):
    original = jpeg()
    compact, kind = cache.thumbnail_variant(17, original, "image/jpeg", 240)
    assert kind == "image/webp"
    assert Image.open(BytesIO(compact)).size == (240, 360)
    assert len(compact) < len(original) / 10
    detail, _ = cache.thumbnail_variant(17, original, "image/jpeg", 960)
    assert Image.open(BytesIO(detail)).size == (960, 1440)
    assert cache.thumbnail_variant(17, original, "image/jpeg", None) == (original, "image/jpeg")
    monkeypatch.setattr(cache.Image, "open", lambda *_: pytest.fail("A cached rendition must not decode again"))
    assert cache.thumbnail_variant(17, original, "image/jpeg", 240) == (compact, "image/webp")


def test_changed_source_bytes_do_not_reuse_an_old_rendition():
    first, _ = cache.thumbnail_variant(17, jpeg(color="red"), "image/jpeg", 240)
    second, _ = cache.thumbnail_variant(17, jpeg(color="blue"), "image/jpeg", 240)
    assert first != second


def test_resize_honors_exif_orientation_and_never_upscales():
    original = Image.new("RGB", (800, 1600), "red")
    exif = original.getexif()
    exif[274] = 6
    buffer = BytesIO()
    original.save(buffer, "JPEG", exif=exif)
    result, _ = cache.thumbnail_variant(1, buffer.getvalue(), "image/jpeg", 240)
    assert Image.open(BytesIO(result)).size == (240, 120)
    result, _ = cache.thumbnail_variant(2, jpeg((80, 60)), "image/jpeg", 240)
    assert Image.open(BytesIO(result)).size == (80, 60)


def test_oversized_decoded_image_is_rejected_before_resizing(monkeypatch):
    monkeypatch.setattr(cache, "MAX_THUMBNAIL_PIXELS", 20)
    with pytest.raises(cache.DreamThumbnailError, match="dimensions"):
        cache.thumbnail_variant(1, jpeg((10, 10)), "image/jpeg", 240)


def test_sibling_places_share_one_url_and_one_small_cover(client, test_db, test_user, monkeypatch):
    dream, rows = saved_places(test_db, test_user)
    original = jpeg()
    reads = []
    def read(item_id):
        reads.append(item_id)
        return (original, "image/jpeg") if item_id == rows[1].id else None
    monkeypatch.setattr("app.routers.dreams.read_cached_thumbnail", read)
    monkeypatch.setattr("app.routers.dreams.fetch_instagram_metadata", lambda *_: pytest.fail("An existing sibling cover must not refetch Instagram"))
    listed = client.get(f"/dreams/{dream.id}/items")
    expected = f"/dream-source-posts/{rows[0].source_post_id}/thumbnail"
    assert {item["thumbnail_url"] for item in listed.json()} == {f"/dream-items/{row.id}/thumbnail" for row in rows}, "Old clients retain their supported image URLs"
    assert {item["source_post_id"] for item in listed.json()} == {rows[0].source_post_id}
    response = client.get(expected + "?width=240")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["vary"] == "Authorization"
    assert response.headers["cache-control"].startswith("private")
    assert Image.open(BytesIO(response.content)).size == (240, 360)
    assert reads == [rows[0].id, rows[1].id]
    assert client.get(expected + "?width=123").status_code == 422
    assert client.get(expected).content == original

    # Remaining rows still have this URL in the app after local deletion.
    test_db.delete(rows[0])
    test_db.commit()
    response = client.get(expected + "?width=240")
    assert response.status_code == 200
    assert Image.open(BytesIO(response.content)).size == (240, 360)


def test_thumbnail_ownership_is_checked_before_disk_cache(client, test_db, test_user, monkeypatch):
    _, rows = saved_places(test_db, test_user)
    other = User(id=2, email="other@example.com", name="Other")
    test_db.add(other)
    test_db.commit()
    rows[0].user_id = other.id
    test_db.commit()
    monkeypatch.setattr("app.routers.dreams.read_cached_thumbnail", lambda *_: pytest.fail("Unauthorized images must never touch the cache"))
    response = client.get(f"/dream-items/{rows[0].id}/thumbnail?width=240")
    assert response.status_code == 404
    assert cache.thumbnail_item_id(rows[1]) == rows[1].id, "Even malformed legacy source groups must exclude another owner's item"

    rows[1].source_post.user_id = other.id
    test_db.commit()
    response = client.get(f"/dream-source-posts/{rows[1].source_post_id}/thumbnail?width=240")
    assert response.status_code == 404
