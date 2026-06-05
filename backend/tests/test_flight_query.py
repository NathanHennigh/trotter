from app.services.flight_query import PRECISE_SUBJECT_KEYWORDS, SENDER_DOMAINS
from app.services.flight_query_v3 import build_gmail_queries


def test_production_queries_are_bounded_and_full_history():
    queries = build_gmail_queries(max_query_length=500)

    assert len(queries) > 1
    assert all(len(query) <= 500 for query in queries)
    assert all(query.startswith("after:2004/1/1 ") for query in queries)
    assert any("from:aa.com" in query for query in queries)
    assert any('"boarding pass"' in query for query in queries)


def test_v3_uses_precise_terms_without_broad_category_travel():
    queries = build_gmail_queries()
    combined_v3 = " OR ".join(
        query.removeprefix("after:2004/1/1 (").removesuffix(")") for query in queries
    )

    assert "category:travel" not in combined_v3
    for keyword in PRECISE_SUBJECT_KEYWORDS:
        assert f'"{keyword}"' in combined_v3
    for domain in SENDER_DOMAINS:
        assert f"from:{domain}" in combined_v3
