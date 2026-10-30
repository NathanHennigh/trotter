"""Keep the traveller's note separate from extracted source text."""
from alembic import op
import sqlalchemy as sa

revision = "0015_dream_personal_notes"
down_revision = "0014_dream_area_precision"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dream_items", sa.Column("personal_note", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("Refusing to discard personal notes. Keep this schema when rolling back application code.")
