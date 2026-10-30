"""Persist selected transport modes while preserving the legacy primary mode."""
from alembic import op
import sqlalchemy as sa

revision = "0020_planner_transport_modes"
down_revision = "0019_planner_dream_matching"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("planner_trips", sa.Column("transport_modes", sa.JSON(), nullable=False, server_default='["walk"]'))
    connection = op.get_bind()
    update = sa.text("UPDATE planner_trips SET transport_modes=:modes WHERE id=:trip_id").bindparams(sa.bindparam("modes", type_=sa.JSON()))
    last = ""
    while True:
        rows = connection.execute(sa.text("SELECT id,transport FROM planner_trips WHERE id>:last ORDER BY id LIMIT 1000"), {"last": last}).mappings().all()
        if not rows:
            break
        # Every historical primary selection survives. No plan/version/timestamp is modified.
        connection.execute(update, [{"trip_id": row["id"], "modes": [row["transport"]]} for row in rows])
        last = rows[-1]["id"]


def downgrade():
    connection = op.get_bind()
    result = connection.execute(sa.text("SELECT 1 FROM planner_trips WHERE json_array_length(transport_modes)<>1 LIMIT 1")).first()
    if result:
        raise RuntimeError("Refusing to discard multiple transport selections; choose one mode per trip before downgrading.")
    op.drop_column("planner_trips", "transport_modes")
