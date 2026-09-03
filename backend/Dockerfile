FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir poetry==2.4.2 \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin trotter

WORKDIR /app

COPY backend/pyproject.toml backend/poetry.lock ./
RUN poetry install --only main --no-interaction --no-ansi --no-root

COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/scripts/migrate_sqlite_to_postgres.py ./scripts/migrate_sqlite_to_postgres.py
COPY backend/docker-entrypoint.sh /usr/local/bin/trotter-entrypoint
COPY domains.csv ./domains.csv

RUN chmod 0755 /usr/local/bin/trotter-entrypoint \
    && mkdir -p /var/lib/trotter \
    && chown -R trotter:trotter /app /var/lib/trotter

USER trotter

ENTRYPOINT ["trotter-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
