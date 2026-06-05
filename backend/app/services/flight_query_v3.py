"""Production Gmail discovery queries for flight emails.

V3 keeps v1's high-signal keyword/domain corpus, but avoids one oversized
Gmail OR expression. Queries are bounded, full-history, and deduped by the
Gmail iterator.
"""

from __future__ import annotations

from .flight_query import PRECISE_SUBJECT_KEYWORDS, SENDER_DOMAINS, SUBJECT_KEYWORDS

DEFAULT_LOOKBACK_START = "2004/1/1"
DEFAULT_MAX_QUERY_LENGTH = 1400


def _with_lookback(query: str, since: str) -> str:
    return f"after:{since} ({query})"


def _chunk_or_terms(
    terms: list[str],
    *,
    since: str,
    max_query_length: int,
) -> list[str]:
    queries: list[str] = []
    current: list[str] = []

    for term in terms:
        candidate = current + [term]
        rendered = _with_lookback(" OR ".join(candidate), since)
        if current and len(rendered) > max_query_length:
            queries.append(_with_lookback(" OR ".join(current), since))
            current = [term]
        else:
            current = candidate

    if current:
        queries.append(_with_lookback(" OR ".join(current), since))
    return queries


def build_gmail_queries(
    *,
    since: str = DEFAULT_LOOKBACK_START,
    max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
) -> list[str]:
    """Return bounded production Gmail queries with v1-equivalent coverage."""
    terms = [f'"{keyword}"' for keyword in PRECISE_SUBJECT_KEYWORDS]
    terms.extend(f"from:{domain}" for domain in SENDER_DOMAINS)
    return _chunk_or_terms(terms, since=since, max_query_length=max_query_length)


def build_gmail_query() -> str:
    """Return the legacy one-shot v1-compatible query for manual preview only."""
    keyword_parts = " OR ".join(f'"{keyword}"' for keyword in SUBJECT_KEYWORDS)
    domain_parts = " OR ".join(f"from:{domain}" for domain in SENDER_DOMAINS)
    return f"({keyword_parts}) OR ({domain_parts})"
