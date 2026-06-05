import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy import text
from alembic import context
from dotenv import load_dotenv


config = context.config
load_dotenv()

if config.config_file_name is not None:
	fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
	return os.getenv(
		"DATABASE_URL",
		"postgresql+psycopg2://trotter:trotter@localhost:5432/trotter",
	)


def run_migrations_offline() -> None:
	url = get_url()
	context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})

	with context.begin_transaction():
		context.run_migrations()


def run_migrations_online() -> None:
	configuration = config.get_section(config.config_ini_section) or {}
	configuration["sqlalchemy.url"] = get_url()

	connectable = engine_from_config(
		configuration,
		prefix="sqlalchemy.",
		poolclass=pool.NullPool,
	)

	with connectable.connect() as connection:
		if connection.dialect.name == "postgresql":
			has_alembic_version = connection.execute(
				text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
			).scalar()
			if has_alembic_version:
				connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))
			else:
				connection.execute(
					text("CREATE TABLE alembic_version (version_num VARCHAR(128) NOT NULL PRIMARY KEY)")
				)
			connection.commit()

		context.configure(connection=connection, target_metadata=target_metadata)

		with context.begin_transaction():
			context.run_migrations()


if context.is_offline_mode():
	run_migrations_offline()
else:
	run_migrations_online()


