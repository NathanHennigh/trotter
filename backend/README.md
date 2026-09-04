# TravelStrava Backend

FastAPI backend for Phase 0 with Google OAuth, Gmail integration, and PostGIS.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker (for PostgreSQL + PostGIS)
- Google Cloud Platform project with OAuth credentials

### Setup

1. **Environment Setup**
   ```bash
   cd backend
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   pip install -r requirements.txt  # or use Poetry
   ```

2. **Environment Variables**
   Create `backend/.env` file:
   ```env
   # Database
   DATABASE_URL=postgresql+psycopg://trotter:trotter@localhost:5432/trotter
   
   # Redis (for Celery)
   REDIS_URL=redis://localhost:6379/0
   
   # Google OAuth (get from Google Cloud Console)
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret
   
   # Gmail API
   GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.readonly

   # Hosted Dreams extraction
   DREAM_AI_PROVIDER=venice
   DREAM_AI_PRIMARY_MODEL=qwen3-5-9b
   DREAM_AI_FALLBACK_MODEL=kimi-k2-5
   VENICE_API_KEY=your-server-side-venice-key
   
   # App Security
   SECRET_KEY=your-jwt-secret-key-change-in-production
   ENCRYPTION_KEY=your-32-byte-base64-or-hex-encryption-key
   
   # Development
   CELERY_ALWAYS_EAGER=False
   ```

3. **Generate Encryption Key**
   ```bash
   python -c "from app.crypto import generate_encryption_key; print('ENCRYPTION_KEY=' + generate_encryption_key())"
   ```

4. **Start Services**
   ```bash
   # Start PostgreSQL + PostGIS
   docker compose up -d db
   
   # Run migrations
   alembic upgrade head
   
   # Seed dev data
   python -m app.seed
   ```

5. **Run Backend**
   ```bash
   uvicorn app.main:app --reload
   ```

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Gmail API
4. Create OAuth 2.0 credentials:
   - **Web application** (for backend token exchange)
   - **Android** (for mobile app - configure separately)
5. Add your client ID and secret to `.env`

### Dreams AI

Dreams parsing uses the Venice OpenAI-compatible chat-completions API by default. The primary model returns strict JSON Schema output; weak or failed parses can selectively retry with the configured fallback model. The API key is read only by the backend.

Local Ollama remains available for parser baselines by setting `DREAM_AI_PROVIDER=ollama`. It is not needed for normal development or production.

### Testing

**With Virtual Environment:**
```bash
# Set environment variables
$env:SECRET_KEY="test-secret-key"
$env:ENCRYPTION_KEY="fRxn/UQDA6936s/OzrMd0F7AUlQAoN0XaPK1V7VFZd4="  # Example key
$env:DATABASE_URL="postgresql+psycopg://trotter:trotter@localhost:5432/trotter"

# Run tests
.venv\Scripts\python -m pytest -v
```

**Test Coverage:**
- ✅ Crypto: AES-256-GCM encryption/decryption (8 tests)
- ✅ Auth: JWT creation/verification (10 tests) 
- ✅ Health endpoint (1 test)
- ✅ Database: PostGIS connection (1 test, requires DB)
- ✅ Migrations: Up/down cycle (1 test, requires DB)
- ✅ Celery: Basic task (1 test, skips without Redis)

### API Endpoints

- `GET /health` - Health check
- `POST /auth/google` - Google OAuth token exchange
- `GET /auth/me` - Current user info (requires JWT)

### Development Commands

```bash
# Format code
python -m black . && python -m isort .

# Type checking
python -m mypy app/

# Run with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
