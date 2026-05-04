from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()


def create_app() -> FastAPI:
	app = FastAPI(title="TravelStrava API", version="0.0.1")

	# Minimal CORS for local dev (mobile debugging)
	app.add_middleware(
		CORSMiddleware,
		allow_origins=["*"],
		allow_credentials=True,
		allow_methods=["*"],
		allow_headers=["*"],
	)

	from .routers.health import router as health_router
	from .routers.auth import router as auth_router
	from .routers.ingest import router as ingest_router
	from .routers.trips import router as trips_router

	app.include_router(health_router)
	app.include_router(auth_router)
	app.include_router(ingest_router)
	app.include_router(trips_router)

	return app


app = create_app()


