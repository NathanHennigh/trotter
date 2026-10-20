"""Explain a save's map availability without changing its destination or data.

These fields are presentation only. They neither schedule retries nor decide
whether a provider result is safe to pin. Callers pass the existing public
location/sorting state, so stale or expired coordinates cannot be revived here.
"""
from __future__ import annotations

import re
import unicodedata

from .dream_location_research import source_area_intent


_ACTIVE = {"queued", "running"}
_GENERIC_NAMES = {
    "hotel", "airbnb", "accommodation", "cafe", "coffee shop", "restaurant",
    "bar", "place", "unknown", "unnamed", "unnamed hotel", "unnamed stay",
    "deluxe room with view", "room with view", "peak lunch location",
    "my favorite place on earth", "my favourite place on earth",
}
_LODGING = re.compile(
    r"\b(?:hotel\w*|airbnb\w*|propert(?:y|ies)|rentals?|treehouses?|villas?|"
    r"hideaway|riads?|rooms?|stays?|lodg(?:e|ing))\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def _text(value):
    return str(value or "")[:20_000]


def _normalized(value):
    value = unicodedata.normalize("NFKD", _text(value)).casefold()
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def _usable_caption(caption):
    # Emoji-only captions are present but uninformative, not failed retrievals.
    return bool(_URL.sub("", caption).strip())


def _explicit_named_evidence(name, caption):
    """A source can establish a property's name even when it is also a town."""
    target = re.escape(_normalized(name))
    if re.search(r"\b(?:called|named|name is)\s+" + target + r"(?!\w)", _normalized(caption)):
        return True
    compact = re.sub(r"\W", "", _normalized(name))
    return any(re.sub(r"[_.]", "", handle).casefold() == compact
               for handle in re.findall(r"(?<!\w)@([\w.]+)", caption))


def _source_only_lodging_label(item, name, caption):
    """Reject geography/CTA keywords copied as a hotel's name, not real brands.

    No city dictionary is needed: the source itself must use this label only
    as geographic context or as a comment keyword. Other name occurrences
    keep the item unresolved rather than presuming an unnamed property.
    """
    if getattr(item, "category", None) != "hotel" or not _LODGING.search(caption):
        return False
    if re.search(r"\b(?:hotel|resort|inn|lodge|suites?|rooms?|villa|riad|studio)\b", name, re.IGNORECASE):
        return False
    target = re.escape(_normalized(name))
    name_pattern = r"(?<!\w)" + target + r"(?!\w)"
    source = re.sub(r"(?<!\w)#[\w]+", "", caption)
    cta_only = False
    if _creator_details_required(caption):
        clauses = re.findall(r"\b(?:comment|dm(?:\s+me)?|message\s+me)\b[^.!?\n]{0,220}", source, re.IGNORECASE)
        for clause in clauses:
            if re.search(name_pattern, _normalized(clause)):
                source = source.replace(clause, "")
                cta_only = True
    residual = _normalized(source)
    geography_patterns = [
        r"\b(?:in|near|around|overlooking)\s+" + target + r"(?!\w)",
        r"\b(?:best|boutique|unique|beautiful)\s+(?:airbnbs?|hotels?|stays?|riads?)\s+" + target + r"(?!\w)",
    ]
    geographic = any(re.search(pattern, residual) for pattern in geography_patterns)
    for pattern in geography_patterns:
        residual = re.sub(pattern, "", residual)
    country = _normalized(getattr(item, "country", None))
    if geographic and country:
        # Having independently established geography, remove an additional
        # caption tag such as "Taghazout Morocco". A brand-country caption
        # alone is not enough to classify a real property as unnamed.
        residual = re.sub(name_pattern + r"\s+" + re.escape(country) + r"(?!\w)", "", residual)
    return bool((cta_only or geographic) and not re.search(name_pattern, residual))


def _named_identity(item, caption):
    """Retain named misses; discard only obvious legacy descriptive labels."""
    name = _text(getattr(item, "place_name", None)).strip()
    normalized = _normalized(name)
    if not normalized or normalized in _GENERIC_NAMES:
        return False
    if _explicit_named_evidence(name, caption):
        return True
    # Older importers sometimes copied the whole caption into place_name.
    if re.match(r"^(?:(?:best|beautiful|aesthetic)\s+)?(?:coffee shops|cafes|restaurants|hotels|stays)\s+(?:in|near|around)\b", normalized):
        return False
    if re.match(r"^(?:(?:the|a|an|our|this)\s+)?(?:(?:most|very|beautiful|dreamy|hidden|best|perfect|unique|luxury)\s+){1,5}(?:riad|hotel|stay|room|airbnb)\s+(?:in|near|around|overlooking)\s+", normalized):
        return False
    area = source_area_intent(
        place_name=name, source_caption=caption,
        city=getattr(item, "city", None), category=getattr(item, "category", None),
        region_or_neighborhood=getattr(item, "region_or_neighborhood", None),
    )
    if not area and _source_only_lodging_label(item, name, caption):
        return False
    if not area and normalized in {
        _normalized(getattr(item, field, None))
        for field in ("city", "country", "region_or_neighborhood")
    }:
        return False
    # "This Airbnb in Lake Atitlan" identifies scenery, not the rental.
    # A source explicitly recommending the lake itself still counts as named.
    if not area and getattr(item, "category", None) == "hotel" and re.match(
        r"^(?:lake|island|valley|mountain|beach)\s+", normalized
    ) and _LODGING.search(caption):
        relation = r"\b(?:in|on|near|overlooking)\s+" + re.escape(name) + r"(?!\w)"
        if re.search(relation, caption, re.IGNORECASE):
            return False
    return True


def _broad_guide(caption):
    # A hotel roundup with concealed names is not an itinerary. A caption
    # listing actual named stops is handled by _named_identity first.
    text = _normalized(caption)
    if re.search(r"\b(?:itinerary|itineraries|roadtrips?|road trips?)\b", text):
        return True
    return bool(not _LODGING.search(caption) and re.search(
        r"\b(?:travel guides?|vacation ideas|holiday ideas|places to visit|travel destinations)\b", text))


def _creator_details_required(caption):
    """Recognize an explicit offer, not a generic engagement question."""
    text = " ".join(caption.casefold().replace("’", "'").split())
    action = r"\b(?:comment|dm(?:\s+me)?|message\s+me)\b"
    detail = r"\b(?:link|location|address|name|details|info|list|booking)\b"
    for match in re.finditer(action, text):
        prefix = text[max(0, match.start() - 50):match.start()]
        if re.search(r"\b(?:no need to|don'?t|do not|never|not necessary to)\s*$", prefix):
            continue
        clause = text[match.start():match.start() + 220]
        # Don't let a later unrelated sentence turn "comment your favorite"
        # into an instruction to contact a creator for a private address.
        clause = re.split(r"[.!?\n]", clause, maxsplit=1)[0]
        if re.search(r"\b(?:for|to (?:get|receive)|(?:i|we)(?:'ll| will) (?:send|share|give))\b", clause) and re.search(detail, clause):
            return True
        if re.search(r"\bto receive\b", clause) and re.search(r"\b(?:list|hotels|stays|places)\b", clause):
            return True
    return False


def _result(state, reason, hint=None):
    return {"location_state": state, "location_reason": reason, "location_hint": hint}


def location_presentation(
    item, *, location_status=None, coordinate_precision=None, sorting_state=None,
    has_pin=False, enrichment_status=None, recovery_waiting=False,
):
    """Return additive UI fields; this function performs no I/O or mutations.

    A current usable pin wins over background refresh failures. Otherwise
    active work and provider failures take priority over source limitations.
    A country may be known in every state; this never changes country grouping.
    """
    if has_pin:
        if coordinate_precision == "area":
            return _result("area", "resolved_area", "The marker shows the general area.")
        return _result("place", "resolved_place")
    if recovery_waiting or sorting_state == "retry_wait":
        return _result("unavailable", "provider_unavailable", "Saved. We’ll try again automatically.")
    if location_status in _ACTIVE or sorting_state in _ACTIVE or enrichment_status in _ACTIVE:
        return _result("processing", "processing", "Finding its location")

    caption = _text(getattr(item, "caption", None)).strip()
    # A missing caption is distinct from a service failure with usable source.
    if sorting_state == "unavailable" and not _usable_caption(caption):
        return _result("source_details", "caption_missing", "The post's caption isn't available. Your save is kept.")
    if location_status == "blocked":
        return _result("unavailable", "provider_unavailable", "Location lookup is temporarily unavailable. Your save is kept.")
    if location_status == "failed":
        return _result("unavailable", "processing_failed", "Saved. We couldn't finish finding its location. You can try again.")
    if sorting_state == "failed" or enrichment_status == "failed":
        return _result("unavailable", "processing_failed", "Saved. We couldn't finish reading this post. You can try again.")
    if location_status in {"resolved", "manual"}:
        return _result("unavailable", "location_unavailable", "Map details aren't available yet. Your save is kept.")
    if location_status == "needs_review":
        return _result("unresolved", "ambiguous_match", "Several places may match. No pin has been chosen.")
    if _named_identity(item, caption):
        return _result("unresolved", "named_unresolved", "Place saved. Its map location hasn't been verified yet.")
    if not _usable_caption(caption):
        return _result("source_details", "caption_missing", "The post's caption isn't available. Your save is kept.")
    if _broad_guide(caption):
        return _result("source_details", "broad_guide", "Saved as a travel guide, rather than one map location.")
    if _creator_details_required(caption):
        return _result("source_details", "creator_link_required", "The creator offers location details by comment or message. Open the post for their instructions.")
    return _result("source_details", "identity_not_shared", "Saved as inspiration. The exact place isn't identified.")
