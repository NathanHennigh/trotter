import os
import subprocess
import sys
import pytest


pytestmark = pytest.mark.skipif(
	os.getenv("DATABASE_URL") is None,
	reason="DATABASE_URL not set; skip seed test",
)


def test_seed_script_runs_once_idempotent():
	# Run alembic upgrade first
	root = os.path.join(os.path.dirname(__file__), "..")
	res = subprocess.run(["poetry", "run", "alembic", "upgrade", "head"], cwd=root)
	assert res.returncode == 0

	# Run seed script twice and ensure no error
	for _ in range(2):
		res = subprocess.run(["poetry", "run", sys.executable, "-m", "app.seed"], cwd=root)
		assert res.returncode == 0


