"""Explicit destination scopes, private matching, and revocable future-save consent."""
import hashlib
import json
import re
import unicodedata

from alembic import op
import sqlalchemy as sa

revision = "0019_planner_dream_matching"
down_revision = "0018_collaborative_planner"
branch_labels = None
depends_on = None


# Frozen canonicalization for the initial indexed projection; never import live ORM models.
COUNTRIES = {"ma": "morocco", "morocco": "morocco", "vn": "vietnam", "viet nam": "vietnam",
    "vietnam": "vietnam", "us": "united states", "usa": "united states", "united states": "united states",
    "united states of america": "united states", "uk": "united kingdom", "gb": "united kingdom",
    "united kingdom": "united kingdom", "ae": "united arab emirates", "uae": "united arab emirates",
    "united arab emirates": "united arab emirates"}
CITIES = {("morocco", "marrakech"): "marrakesh", ("morocco", "marrakesh"): "marrakesh",
    ("vietnam", "ha noi"): "hanoi", ("vietnam", "hanoi"): "hanoi"}


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", "".join(c for c in value if not unicodedata.combining(c))).split())


def keys(country, city, title, region=None):
    country, city, title = normalized(country), normalized(city), normalized(title)
    country = COUNTRIES.get(country, country)
    city = CITIES.get((country, city), city)
    unknown = {"", "unknown", "unspecified", "not specified", "n a", "none", "null", "worldwide"}
    country = country[:128] if country not in unknown else None
    city = city[:128] if city not in unknown else None
    key = hashlib.sha256(json.dumps([title, country, city, normalized(region) or None], ensure_ascii=False).encode()).hexdigest() if title and country else None
    return country, city, key


def upgrade():
    for name, length in (("planner_country_key", 128), ("planner_city_key", 128), ("planner_place_key", 64)):
        op.add_column("dream_items", sa.Column(name, sa.String(length), nullable=True))
    for name in ("match_country_key", "match_city_key"):
        op.add_column("planner_trips", sa.Column(name, sa.String(128), nullable=True))
    op.add_column("planner_members", sa.Column("dream_auto_share", sa.Boolean(), nullable=False, server_default=sa.false()))
    for name in ("dream_consented_at", "dream_last_synced_at"):
        op.add_column("planner_members", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("planner_members", sa.Column("dream_sync_item_id", sa.BigInteger(), nullable=True))
    op.add_column("planner_ideas", sa.Column("dream_match_key", sa.String(64), nullable=True))
    op.add_column("planner_ideas", sa.Column("region_or_neighborhood", sa.String(128), nullable=True))
    connection = op.get_bind()
    last = 0
    while True:
        rows = connection.execute(sa.text("SELECT id,country,city,place_name,region_or_neighborhood FROM dream_items WHERE id>:last ORDER BY id LIMIT 1000"), {"last": last}).mappings().all()
        if not rows:
            break
        values = []
        for row in rows:
            country, city, key = keys(row["country"], row["city"], row["place_name"], row["region_or_neighborhood"])
            values.append({"row_id": row["id"], "country_key": country, "city_key": city, "place_key": key})
        connection.execute(sa.text("UPDATE dream_items SET planner_country_key=:country_key, planner_city_key=:city_key, planner_place_key=:place_key WHERE id=:row_id"), values)
        last = rows[-1]["id"]
    last = ""
    while True:
        rows = connection.execute(sa.text("SELECT id,country,city,title FROM planner_ideas WHERE id>:last ORDER BY id LIMIT 1000"), {"last": last}).mappings().all()
        if not rows:
            break
        connection.execute(sa.text("UPDATE planner_ideas SET dream_match_key=:place_key WHERE id=:row_id"),
            [{"row_id": row["id"], "place_key": keys(row["country"], row["city"], row["title"])[2]} for row in rows])
        last = rows[-1]["id"]
    op.create_index("ix_dream_planner_geography", "dream_items", ["user_id", "planner_country_key", "planner_city_key", "id"])
    op.create_index("ix_planner_member_dream_sync", "planner_members", ["dream_auto_share", "dream_last_synced_at"])
    op.create_index("ix_planner_idea_dream_match", "planner_ideas", ["trip_id", "dream_match_key"])
    op.create_index("ix_planner_idea_provider_match", "planner_ideas", ["trip_id", "google_place_id"])
    op.create_index("ix_planner_contribution_dream", "planner_contributions", ["trip_id", "user_id", "dream_item_id"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM planner_trips WHERE match_country_key IS NOT NULL LIMIT 1")).first() or connection.execute(
            sa.text("SELECT 1 FROM planner_members WHERE dream_auto_share=true OR dream_consented_at IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Refusing to discard matching scopes or future-sharing consent; clear them explicitly before downgrading.")
    for name, table in (("ix_dream_planner_geography", "dream_items"), ("ix_planner_member_dream_sync", "planner_members"),
                        ("ix_planner_idea_dream_match", "planner_ideas"), ("ix_planner_idea_provider_match", "planner_ideas"),
                        ("ix_planner_contribution_dream", "planner_contributions")):
        op.drop_index(name, table_name=table)
    for table, names in (("dream_items", ("planner_country_key", "planner_city_key", "planner_place_key")),
        ("planner_trips", ("match_country_key", "match_city_key")),
        ("planner_members", ("dream_auto_share", "dream_consented_at", "dream_last_synced_at", "dream_sync_item_id")),
        ("planner_ideas", ("dream_match_key", "region_or_neighborhood"))):
        for name in names:
            op.drop_column(table, name)
