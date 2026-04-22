#!/usr/bin/env python3
"""Simple script to test the FastAPI server."""

import os
import uvicorn

# Set environment variables
os.environ["DATABASE_URL"] = "postgresql+psycopg://trotter:trotter@localhost:5432/trotter"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENCRYPTION_KEY"] = "fRxn/UQDA6936s/OzrMd0F7AUlQAoN0XaPK1V7VFZd4="
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"

if __name__ == "__main__":
    print("🚀 Starting TravelStrava Backend...")
    print("📍 Health check: http://127.0.0.1:8000/health")
    print("📚 API docs: http://127.0.0.1:8000/docs")
    print("⏹️  Press Ctrl+C to stop")
    
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )
