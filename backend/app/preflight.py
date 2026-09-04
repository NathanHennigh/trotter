"""Fail-fast production configuration validation for container startup."""

import os
from urllib.parse import urlparse

from .crypto import get_encryption_key


def _required(name: str) -> str:
    raw_value = os.getenv(name, "")
    value = raw_value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    if raw_value != value:
        raise ValueError(f"{name} must not contain surrounding whitespace")
    return value


def validate_production_environment() -> None:
    if os.getenv("TROTTER_ENV", "development").lower() != "production":
        return

    backend_url = _required("BACKEND_URL").rstrip("/")
    web_app_url = _required("WEB_APP_URL").rstrip("/")
    for name, value in (("BACKEND_URL", backend_url), ("WEB_APP_URL", web_app_url)):
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError(f"{name} must be an HTTPS origin without a path")

    database_url = _required("DATABASE_URL")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Production DATABASE_URL must use PostgreSQL")

    _required("REDIS_URL")
    _required("GOOGLE_CLIENT_ID")
    _required("GOOGLE_CLIENT_SECRET")
    jwt_secret = _required("JWT_SECRET")
    if len(jwt_secret) < 32:
        raise ValueError("JWT_SECRET must contain at least 32 characters")
    get_encryption_key()

    if os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes"):
        raise ValueError("DEV_MODE must be false in production")
    if "*" in os.getenv("CORS_ALLOWED_ORIGINS", "*").split(","):
        raise ValueError("Production CORS_ALLOWED_ORIGINS cannot contain '*'")
    if "*" in os.getenv("ALLOWED_HOSTS", "*").split(","):
        raise ValueError("Production ALLOWED_HOSTS cannot contain '*'")


if __name__ == "__main__":
    validate_production_environment()
    print("Trotter production configuration is valid.")
