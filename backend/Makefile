PY=poetry run

.PHONY: migrate migrate-down seed
lint:
	$(PY) black --check app tests
	$(PY) isort --check-only app tests
	$(PY) mypy app

fmt:
	$(PY) black app tests
	$(PY) isort app tests

migrate:
	$(PY) alembic upgrade head

migrate-down:
	$(PY) alembic downgrade -1

seed:
	$(PY) python -m app.seed


