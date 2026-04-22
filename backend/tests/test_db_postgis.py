import os
import pytest


pytestmark = pytest.mark.skipif(
	os.getenv("DATABASE_URL") is None,
	reason="DATABASE_URL not set; skip PostGIS availability test",
)


def test_postgis_version_available():
	from app.db import create_test_connection
	assert create_test_connection() is True


