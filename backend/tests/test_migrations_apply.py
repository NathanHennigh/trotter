import os
import pytest
from subprocess import CalledProcessError, run


pytestmark = pytest.mark.skipif(
	os.getenv("DATABASE_URL") is None,
	reason="DATABASE_URL not set; skip migration smoke test",
)


def test_alembic_upgrade_head():
	# Smoke test: migrations apply without error
	res = run(["poetry", "run", "alembic", "upgrade", "head"], cwd=os.path.dirname(__file__) + "/..")
	assert res.returncode == 0


