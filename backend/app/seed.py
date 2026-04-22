from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import create_engine, text


@dataclass
class SeedConfig:
	url: str


def seed_dev_data(cfg: SeedConfig) -> None:
	engine = create_engine(cfg.url, future=True)
	with engine.begin() as conn:
		conn.execute(
			text(
				"""
				INSERT INTO users (email, name)
				VALUES (:email, :name)
				ON CONFLICT (email) DO NOTHING
				"""
			),
			{"email": "dev@example.com", "name": "Dev User"},
		)


def main() -> None:
	url = os.getenv(
		"DATABASE_URL",
		"postgresql+psycopg2://trotter:trotter@localhost:5432/trotter",
	)
	seed_dev_data(SeedConfig(url=url))
	print("Seeded dev data")


if __name__ == "__main__":
	main()


