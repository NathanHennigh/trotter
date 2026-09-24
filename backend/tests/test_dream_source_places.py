"""Multiple places from one retained source: recovery, ownership and edits."""
from copy import deepcopy

from sqlalchemy.orm import sessionmaker

from app.models import DreamItem, DreamSourcePost, DreamLocation, DreamEnrichmentJob
from app.services.dream_enrichment import enqueue_enrichment, resolve_enrichment_job
from app.services.dream_parser import DreamParseItem, DreamParseResponse
from app.services.dream_source_places import expand_saved_sources, place_key
from test_dreams import client, test_db, test_user


def output(names=("El Fenn", "Bacha Coffee", "Le Jardin")):
    return {"caption": "Three places in Marrakech, Morocco: " + ", ".join(names),
            "metadata": {"thumbnail_url": "https://example.invalid/reel.jpg"},
            "parsed": DreamParseResponse(provider="synthetic", model="synthetic", items=[
                DreamParseItem(place_name=name, city="Marrakech", country="Morocco", category="cafe",
                               summary=f"Visit {name}.", confidence=.97, needs_review=False,
                               needs_google_places_lookup=True) for name in names])}


def capture(client, test_db, monkeypatch):
    monkeypatch.setattr("app.routers.dreams.notify_enrichment", lambda _: None)
    saved = client.post("/dreams/share", json={"source_url": "https://instagram.com/reel/multi", "caption": output()["caption"]}).json()
    job_id = test_db.query(DreamEnrichmentJob).filter_by(item_id=saved["dream_item_id"]).one().id
    return saved, job_id, sessionmaker(bind=test_db.get_bind(), autoflush=False)


def run(factory, job_id, value=None, reader=None):
    return resolve_enrichment_job(job_id, session_factory=factory, reader=reader or (lambda _: value or output()))


def retry(factory, item_id):
    with factory() as db:
        row, _ = enqueue_enrichment(db, db.get(DreamItem, item_id), force=True)
        db.commit()
        return row.id


def test_flat_cards_individual_jobs_one_source_and_duplicate_share(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    assert run(factory, job_id) == "completed"
    cards = client.get("/dream-items").json()
    assert len(cards) == 3
    assert cards[0]["id"] == saved["dream_item_id"]
    assert [card["place_name"] for card in cards] == ["El Fenn", "Bacha Coffee", "Le Jardin"]
    assert len({card["source_url"] for card in cards}) == len({card["source_post_id"] for card in cards}) == 1
    assert all(card["source_place_count"] == 3 and card["thumbnail_url"] for card in cards)
    assert [card["source_place_index"] for card in cards] == [0, 1, 2]
    assert len({card["id"] for card in cards}) == 3
    assert test_db.query(DreamLocation).count() == 3
    assert test_db.query(DreamSourcePost).count() == 1
    assert client.get("/dreams").json()[0]["item_count"] == 3
    again = client.post("/dreams/share", json={"source_url": cards[0]["source_url"]}).json()
    assert again["duplicate"] and again["dream_item_id"] == saved["dream_item_id"]
    assert test_db.query(DreamItem).count() == 3


def test_reorder_and_duplicates_retain_card_ids_and_no_extra_pin_jobs(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    assert run(factory, job_id) == "completed"
    before = {card["place_name"]: card["id"] for card in client.get("/dream-items").json()}
    assert run(factory, retry(factory, saved["dream_item_id"]), output(("Le Jardin", "El Fenn", "Bacha Coffee", "Bacha Coffee"))) == "completed"
    cards = client.get("/dream-items").json()
    assert before == {card["place_name"]: card["id"] for card in cards}
    assert test_db.query(DreamLocation).count() == 3


def test_deleted_child_not_revived_and_edited_child_preserved(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    run(factory, job_id)
    cards = client.get("/dream-items").json()
    removed, edited = cards[1], cards[2]
    assert client.delete(f'/dream-items/{removed["id"]}').status_code == 204
    response = client.post(f'/dream-items/{edited["id"]}/review', json={"decision": "confirm", "edits": {
        "place_name": "My selected garden", "summary": "Meet friends here", "google_maps_url": "https://maps.google.com/?q=31.63,-7.98"}})
    assert response.status_code == 200
    assert run(factory, retry(factory, saved["dream_item_id"])) == "completed"
    cards = client.get("/dream-items").json()
    assert len(cards) == 2
    kept = next(card for card in cards if card["id"] == edited["id"])
    assert kept["place_name"] == "My selected garden" and kept["summary"] == "Meet friends here"
    assert kept["location_status"] == "manual" and kept["latitude"] == 31.63
    assert all(card["source_place_count"] == 2 for card in cards)


def test_delete_primary_keeps_siblings_and_retry_does_not_revive_it(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    run(factory, job_id)
    assert client.delete(f'/dream-items/{saved["dream_item_id"]}').status_code == 204
    cards = client.get("/dream-items").json()
    assert len(cards) == 2
    assert run(factory, retry(factory, cards[0]["id"])) == "completed"
    cards = client.get("/dream-items").json()
    assert [card["place_name"] for card in cards] == ["Bacha Coffee", "Le Jardin"]
    duplicate = client.post("/dreams/share", json={"source_url": cards[0]["source_url"]}).json()
    assert duplicate["duplicate"] and duplicate["dream_item_id"] == cards[0]["id"]


def test_new_source_generation_supersedes_other_place_worker(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    run(factory, job_id)
    cards = client.get("/dream-items").json()
    job_id = retry(factory, saved["dream_item_id"])
    def racing(_):
        retry(factory, cards[1]["id"])
        return output(("Stale new venue",))
    assert run(factory, job_id, reader=racing) == "superseded"
    assert len(client.get("/dream-items").json()) == 3
    assert not any(card["place_name"] == "Stale new venue" for card in client.get("/dream-items").json())


def test_omitted_place_retained_without_infinite_processing(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    run(factory, job_id)
    assert run(factory, retry(factory, saved["dream_item_id"]), output(("Bacha Coffee",))) == "completed"
    cards = client.get("/dream-items").json()
    assert len(cards) == 3 and all(card["status"] != "processing" for card in cards)


def test_weaker_fallback_cannot_add_a_phantom_place_or_replace_known_venues(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    run(factory, job_id)
    value = output()
    value["parsed"] = DreamParseResponse(items=[DreamParseItem(country="Morocco")], model="fallback")
    assert run(factory, retry(factory, saved["dream_item_id"]), value) == "completed"
    cards = client.get("/dream-items").json()
    assert [card["place_name"] for card in cards] == ["El Fenn", "Bacha Coffee", "Le Jardin"]
    assert all(card["status"] != "processing" for card in cards)


def test_saved_parser_backfill_adds_only_missing_places_and_preserves_primary(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    # Reproduce an older completed save with all extracted items in parser_raw,
    # but only its first venue retained as a visible card.
    with factory() as db:
        item = db.get(DreamItem, saved["dream_item_id"])
        item.status, item.place_name, item.summary = "confirmed", "Chosen hotel name", "Personal notes"
        item.raw_metadata_json = {"dream_user_edited": True, "parser_raw": {"items": [entry.model_dump() for entry in output()["parsed"].items]}}
        item.enrichment.status = "completed"
        db.commit()
        first = expand_saved_sources(db, user_id=test_user.id)
        db.commit()
        second = expand_saved_sources(db, user_id=test_user.id)
        db.commit()
        assert first[0]["added"] == 2 and second[0]["added"] == 0
    cards = client.get("/dream-items").json()
    original = next(card for card in cards if card["id"] == saved["dream_item_id"])
    assert original["place_name"] == "Chosen hotel name" and original["summary"] == "Personal notes"
    assert len(cards) == 3


def test_places_can_span_countries_and_child_endpoints_stay_owner_scoped(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    value = output(("El Fenn", "Cafe de Flore"))
    value["parsed"].items[1] = value["parsed"].items[1].model_copy(update={"city": "Paris", "country": "France"})
    run(factory, job_id, value)
    cards = client.get("/dream-items").json()
    assert len({card["dream_id"] for card in cards}) == 2
    assert all(card["source_place_count"] == 2 for card in cards)
    for card in cards:
        assert len(client.get(f'/dreams/{card["dream_id"]}/items').json()) == 1
    from app.models import User
    from app.main import app
    from app.routers.auth import get_current_user
    other = User(id=2, email="private@example.invalid")
    test_db.add(other)
    test_db.commit()
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.get("/dream-items").json() == []
    assert client.delete(f'/dream-items/{cards[1]["id"]}').status_code == 404
    assert client.post(f'/dream-items/{cards[1]["id"]}/locate').status_code == 404


def test_repeated_name_normalization_but_distinct_branches():
    a = DreamParseItem(place_name="Café de Flore", city="Paris", country="France")
    b = a.model_copy(update={"place_name": " CAFE   DE FLORE "})
    assert place_key(a) == place_key(b)
    assert place_key(a) != place_key(b.model_copy(update={"region_or_neighborhood": "Other branch"}))


def test_legacy_named_anchor_matches_identity_before_positional_expansion(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    with factory() as db:
        item = db.get(DreamItem, saved["dream_item_id"])
        place = output()["parsed"].items[0]
        item.place_name, item.city, item.country = place.place_name, place.city, place.country
        item.status, item.needs_review = "parsed", False
        item.raw_metadata_json = {"parser_raw": {"items": [place.model_dump()]}}
        item.enrichment.status = "completed"
        db.commit()
    assert run(factory, retry(factory, saved["dream_item_id"]), output(("Bacha Coffee", "El Fenn", "Le Jardin"))) == "completed"
    cards = client.get("/dream-items").json()
    assert {card["place_name"] for card in cards} == {"El Fenn", "Bacha Coffee", "Le Jardin"}
    assert next(card for card in cards if card["id"] == saved["dream_item_id"])["place_name"] == "El Fenn"


def test_known_geography_aliases_preserve_ids_and_removal_tombstones(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    run(factory, job_id)
    before = {card["place_name"]: card["id"] for card in client.get("/dream-items").json()}
    assert client.delete(f'/dream-items/{before["Bacha Coffee"]}').status_code == 204
    value = output()
    value["parsed"].items = [item.model_copy(update={"city": "Marrakesh", "country": "MA"}) for item in value["parsed"].items]
    assert run(factory, retry(factory, saved["dream_item_id"]), value) == "completed"
    cards = client.get("/dream-items").json()
    assert {card["place_name"]: card["id"] for card in cards} == {name: id for name, id in before.items() if name != "Bacha Coffee"}
    assert all(card["country"] == "Morocco" and card["city"] == "Marrakech" for card in cards)
    assert len({card["dream_id"] for card in cards}) == 1


def test_city_aliases_are_country_scoped_and_keep_branches_distinct():
    place = DreamParseItem(place_name="Garden Cafe", city="Marrakech", country="Morocco", region_or_neighborhood="Medina")
    assert place_key(place) == place_key(place.model_copy(update={"city": "Marrakesh", "country": "MA"}))
    assert place_key(place) != place_key(place.model_copy(update={"region_or_neighborhood": "Gueliz"}))
    other = place.model_copy(update={"country": "Other Country"})
    assert place_key(other) != place_key(other.model_copy(update={"city": "Marrakesh"}))
    hanoi = DreamParseItem(place_name="Cafe A", city="Hà Nội", country="Viet Nam")
    assert place_key(hanoi) == place_key(hanoi.model_copy(update={"city": "Hanoi", "country": "Vietnam"}))


def test_missing_geography_cannot_arbitrarily_choose_between_named_branches(client, test_db, test_user, monkeypatch):
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    value = output(("Bacha Coffee",))
    value["parsed"].items[0] = value["parsed"].items[0].model_copy(update={"city": None, "country": "Morocco"})
    run(factory, job_id, value)
    branches = output(("Bacha Coffee", "Bacha Coffee"))
    branches["parsed"].items[1] = branches["parsed"].items[1].model_copy(update={"city": "Casablanca"})
    run(factory, retry(factory, saved["dream_item_id"]), branches)
    cards = client.get("/dream-items").json()
    assert len(cards) == 3
    original = next(card for card in cards if card["id"] == saved["dream_item_id"])
    assert original["city"] is None
    assert {card["city"] for card in cards} == {None, "Marrakech", "Casablanca"}


def test_sibling_review_during_provider_work_survives_and_lock_order_is_owner_first(client, test_db, test_user, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from sqlalchemy.dialects import postgresql
    saved, job_id, factory = capture(client, test_db, monkeypatch)
    run(factory, job_id)
    child = client.get("/dream-items").json()[1]
    job_id = retry(factory, saved["dream_item_id"])
    locked = []
    def record(execute):
        statement = execute.statement
        if execute.is_select and getattr(statement, "_for_update_arg", None) is not None:
            locked.append(str(statement.compile(dialect=postgresql.dialect())))
    event.listen(Session, "do_orm_execute", record)
    try:
        def reader(_):
            locked.clear()
            response = client.post(f'/dream-items/{child["id"]}/review', json={"decision": "confirm", "edits": {
                "place_name": "My chosen branch", "summary": "My protected note", "google_maps_url": "https://maps.google.com/?q=31.64,-7.99"}})
            assert response.status_code == 200
            assert "FROM users" in locked[0]
            assert "FROM dream_items" in locked[1]
            locked.clear()
            return output()
        assert run(factory, job_id, reader=reader) == "completed"
        assert "FROM users" in locked[0]
        sibling_locks = [sql for sql in locked if "WHERE dream_items.user_id" in sql and "dream_items.source_post_id =" in sql]
        assert len(sibling_locks) == 1 and "ORDER BY dream_items.id FOR UPDATE" in sibling_locks[0]
    finally:
        event.remove(Session, "do_orm_execute", record)
    current = next(card for card in client.get("/dream-items").json() if card["id"] == child["id"])
    assert current["place_name"] == "My chosen branch" and current["summary"] == "My protected note"
    assert current["latitude"] == 31.64 and current["location_status"] == "manual"
