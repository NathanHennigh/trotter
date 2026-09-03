import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from dotenv import load_dotenv

load_dotenv()


def create_app() -> FastAPI:
	production = os.getenv("TROTTER_ENV", "development").lower() == "production"
	docs_enabled = os.getenv("TROTTER_ENABLE_DOCS", "false" if production else "true").lower() in (
		"1",
		"true",
		"yes",
	)
	app = FastAPI(
		title="Trotter API",
		version="0.1.0",
		docs_url="/docs" if docs_enabled else None,
		redoc_url="/redoc" if docs_enabled else None,
		openapi_url="/openapi.json" if docs_enabled else None,
	)

	allowed_origins = [
		origin.strip().rstrip("/")
		for origin in os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")
		if origin.strip()
	]
	allow_any_origin = "*" in allowed_origins
	app.add_middleware(
		CORSMiddleware,
		allow_origins=["*"] if allow_any_origin else allowed_origins,
		allow_credentials=not allow_any_origin,
		allow_methods=["*"],
		allow_headers=["*"],
	)

	allowed_hosts = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "*").split(",") if host.strip()]
	app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["*"])

	from .routers.health import router as health_router
	from .routers.auth import router as auth_router
	from .routers.ingest import router as ingest_router
	from .routers.trips import router as trips_router
	from .routers.dreams import router as dreams_router

	app.include_router(health_router)
	app.include_router(auth_router)
	app.include_router(ingest_router)
	app.include_router(trips_router)
	app.include_router(dreams_router)

	return app


app = create_app()


