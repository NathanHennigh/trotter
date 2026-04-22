import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://trotter:trotter@localhost:5432/trotter")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_test_connection() -> bool:
    """Creates a test connection and verifies PostGIS is enabled."""
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT PostGIS_Version();")).scalar_one()
            print(f"PostGIS Version: {result}")
            return True
    except Exception as e:
        print(f"Could not connect to DB or PostGIS not enabled: {e}")
        return False


