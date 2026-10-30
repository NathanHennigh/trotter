"""Exact, indexed geographic matching; no model calls or fuzzy destination guesses."""
import hashlib
import json


def geography(country, city):
    # Reuse the same canonical aliases as multi-place source reconciliation.
    from .dream_source_places import COUNTRY_ALIASES, CITY_ALIASES, normalized
    country = normalized(country)
    country = COUNTRY_ALIASES.get(country, country)
    city = normalized(city)
    city = CITY_ALIASES.get((country, city), city)
    unknown = {"", "unknown", "unspecified", "not specified", "n a", "none", "null", "worldwide"}
    return (country[:128] if country not in unknown else None,
            city[:128] if city not in unknown else None)


def maintain_geography(_mapper, _connection, item):
    item.planner_country_key, item.planner_city_key = geography(item.country, item.city)
    item.planner_place_key = place_match_key(item.place_name, item.country, item.city, item.region_or_neighborhood)


def place_match_key(title, country, city, region=None):
    from .dream_source_places import normalized
    country, city = geography(country, city)
    if not normalized(title) or not country:
        return None
    return hashlib.sha256(json.dumps([normalized(title), country, city, normalized(region) or None], ensure_ascii=False).encode()).hexdigest()


def maintain_idea_match_key(_mapper, _connection, idea):
    idea.dream_match_key = place_match_key(idea.title, idea.country, idea.city, idea.region_or_neighborhood)


def register_model_events(dream_model, idea_model):
    """Register only once, after both model modules have finished defining classes."""
    from sqlalchemy import event
    for model, callback in ((dream_model, maintain_geography), (idea_model, maintain_idea_match_key)):
        for name in ("before_insert", "before_update"):
            if not event.contains(model, name, callback):
                event.listen(model, name, callback)
