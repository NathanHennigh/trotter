"""
High-recall flight email detector for Gmail.

Strategy:
  1. build_gmail_queries() -> several bounded Gmail searches
  2. looks_like_flight_email() -> post-fetch regex/content filter

No airport-code whitelist. This is designed to catch flights anywhere.
"""

import re

from .flight_query import SENDER_DOMAINS, SUBJECT_KEYWORDS


AIRLINE_DOMAINS = SENDER_DOMAINS
CORE_FLIGHT_TERMS = SUBJECT_KEYWORDS + [
    "flight",
    "boarding pass",
    "mobile boarding pass",
    "boarding group",
    "boarding time",
    "check in",
    "check-in",
    "online check-in",
    "gate",
    "terminal",
    "departure",
    "arrival",
    "departing",
    "arriving",
    "passenger",
    "seat assignment",
    "seat change",
    "bag drop",
    "baggage",
    "e-ticket",
    "eticket",
    "electronic ticket",
    "ticket number",
    "passenger receipt",
    "trip receipt",
    "record locator",
    "confirmation code",
    "booking reference",
    "reservation code",
    "pnr",
    "manage booking",
    "manage your booking",
    "manage your trip",
    "your trip",
    "your upcoming trip",
    "your flight",
    "schedule change",
    "flight update",
    "flight changed",
    "flight delayed",
    "flight cancelled",
    "flight canceled",
]


# Common airline IATA carrier codes + flight number.
# This catches AA1234, AA 1234, DL75, WN 431, etc.
FLIGHT_NUMBER_RE = re.compile(
    r"""
    (?:
        \b(?:flight|flt|flight\s*no\.?|flight\s*number)\s*[:#-]?\s*
        [A-Z0-9]{2,3}\s?\d{1,4}[A-Z]?\b
    )
    |
    (?:
        \b[A-Z0-9]{2,3}\s?\d{1,4}[A-Z]?\b
        (?=.{0,80}\b(?:flight|boarding|departure|arrival|gate|terminal|airline|passenger|seat)\b)
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


PNR_RE = re.compile(
    r"""
    \b
    (?:
        record\ locator|
        confirmation\ code|
        booking\ reference|
        booking\ code|
        reservation\ code|
        reservation\ number|
        confirmation\ number|
        airline\ confirmation|
        pnr
    )
    [:\s#-]*
    [A-Z0-9]{5,8}
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


TICKET_NUMBER_RE = re.compile(
    r"""
    \b
    (?:
        ticket\ number|
        e-ticket\ number|
        eticket\ number|
        electronic\ ticket\ number
    )
    [:\s#-]*
    \d{3}[-\s]?\d{10}
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


BOARDING_OR_CHECKIN_RE = re.compile(
    r"""
    \b
    (?:
        boarding\ pass|
        mobile\ boarding\ pass|
        boarding\ group|
        boarding\ time|
        boarding\ begins|
        check[-\s]?in|
        online\ check[-\s]?in|
        bag\ drop|
        baggage\ drop|
        seat\ assignment|
        departure\ gate|
        arrival\ gate|
        gate\ change
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


DEFAULT_LOOKBACK_START = "2004/1/1"
DEFAULT_MAX_QUERY_LENGTH = 1400


def _quote_term(term: str) -> str:
    return f'"{term}"'


def _with_lookback(query: str, since: str = DEFAULT_LOOKBACK_START) -> str:
    return f"after:{since} ({query})"


def _chunk_or_terms(
    terms: list[str],
    *,
    since: str = DEFAULT_LOOKBACK_START,
    max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
) -> list[str]:
    """Return Gmail OR queries that stay comfortably below Gmail/API limits."""
    queries: list[str] = []
    current: list[str] = []

    for term in terms:
        candidate_terms = current + [term]
        candidate = _with_lookback(" OR ".join(candidate_terms), since)
        if current and len(candidate) > max_query_length:
            queries.append(_with_lookback(" OR ".join(current), since))
            current = [term]
        else:
            current = candidate_terms

    if current:
        queries.append(_with_lookback(" OR ".join(current), since))
    return queries


def build_gmail_queries(
    *,
    since: str = DEFAULT_LOOKBACK_START,
    max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
) -> list[str]:
    """
    Build production Gmail searches as multiple bounded queries.

    Gmail accepts long expressions, but very large OR queries are brittle and
    can quietly reduce recall in practice. Splitting by concern makes discovery
    resumable at the application level and lets the importer dedupe message IDs.
    """
    queries = [_with_lookback("category:travel", since)]
    queries.extend(
        _chunk_or_terms(
            [f"from:{domain}" for domain in AIRLINE_DOMAINS],
            since=since,
            max_query_length=max_query_length,
        )
    )
    queries.extend(
        _chunk_or_terms(
            [_quote_term(term) for term in CORE_FLIGHT_TERMS],
            since=since,
            max_query_length=max_query_length,
        )
    )
    return queries


def build_gmail_query() -> str:
    """
    Broad Gmail query for manual preview/backwards compatibility.

    Production import uses build_gmail_queries() so Gmail never receives one
    huge brittle query.
    """

    category = "category:travel"
    from_parts = " OR ".join(f"from:{domain}" for domain in AIRLINE_DOMAINS)
    term_parts = " OR ".join(f'"{term}"' for term in CORE_FLIGHT_TERMS)

    # I would NOT exclude hotels/cars here if your goal is "miss no flights."
    # Some OTA emails bundle flight + hotel together.
    return f"({category} OR {from_parts} OR {term_parts})"


def looks_like_flight_email(subject: str = "", sender: str = "", body: str = "") -> bool:
    """
    Returns True if the email likely contains a flight booking, confirmation,
    boarding pass, itinerary, receipt, check-in prompt, or flight update.
    """

    raw_text = f"{subject}\n{sender}\n{body}"
    text = raw_text.lower()
    sender_l = sender.lower()

    # 1. Strong structured identifiers
    if FLIGHT_NUMBER_RE.search(raw_text):
        return True

    if PNR_RE.search(raw_text):
        return True

    if TICKET_NUMBER_RE.search(raw_text):
        return True

    # 2. Boarding / check-in / airport-operation language
    if BOARDING_OR_CHECKIN_RE.search(raw_text):
        return True

    # 3. Any known flight phrase from your master list
    if any(term.lower() in text for term in CORE_FLIGHT_TERMS):
        return True

    # 4. Sender-domain support.
    # Important: do not auto-accept all OTA emails, because Expedia/Booking/etc.
    # may be hotel-only. Require travel context.
    if any(domain in sender_l for domain in AIRLINE_DOMAINS):
        travel_context_terms = [
            "flight",
            "airline",
            "boarding",
            "check-in",
            "check in",
            "itinerary",
            "e-ticket",
            "eticket",
            "ticket",
            "passenger",
            "gate",
            "terminal",
            "departure",
            "arrival",
            "reservation",
            "booking",
            "record locator",
            "pnr",
        ]

        if any(term in text for term in travel_context_terms):
            return True

    return False


if __name__ == "__main__":
    for i, query in enumerate(build_gmail_queries(), 1):
        print(f"[{i}] {len(query)} chars: {query}")
    print("\n--- Tests ---")
    print(looks_like_flight_email(subject="Your AA 1234 boarding pass", body="Gate B12"))
    print(looks_like_flight_email(subject="Your trip is ready", body="Record locator ABC123"))
    print(looks_like_flight_email(subject="E-ticket receipt", body="Ticket number 001-1234567890"))
    print(looks_like_flight_email(subject="Weekly newsletter", body="Unsubscribe here"))
