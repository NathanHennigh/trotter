# Trotter Home Server

For an Oracle Cloud Always Free deployment, start with [`OCI.md`](OCI.md), then
return here for the shared configuration, migration, and operations steps.

This deployment runs the Trotter API, Gmail processing worker, Postgres/PostGIS, Redis, and a browser-build of the app continuously on a Linux home server. A Cloudflare Tunnel publishes two HTTPS origins without router port forwarding:

- `https://api.example.com` -> `http://api:8000`
- `https://app.example.com` -> `http://web:80`

The API and web ports are also bound to `127.0.0.1` on the server for local diagnostics. Postgres and Redis are never published to the host network.

## Prerequisites

- A Linux home server with Docker Engine and the Docker Compose plugin.
- A domain using Cloudflare DNS and a Cloudflare account.
- Outbound internet access from the server. Cloudflare Tunnel uses outbound connections, so no inbound router rule is required.
- The current `backend/trotter.db` and the exact current `ENCRYPTION_KEY` when migrating existing data.
- A Google OAuth web client.

## 1. Prepare Configuration

Clone the repository to the server, then work from `deploy`:

```bash
cd /opt/trotter/deploy
cp home-server.env.example home-server.env
chmod +x scripts/*.sh
./scripts/init-secrets.sh
```

Edit `home-server.env` with the real API hostname, web hostname, and Google client ID. Fill these ignored files under `secrets/`:

- `google_client_secret`
- `cloudflare_tunnel_token`

For an existing Trotter database, replace the generated `secrets/encryption_key` with the exact `ENCRYPTION_KEY` from the old `backend/.env`. Do this before importing. Changing this key makes existing encrypted Google refresh tokens unreadable.

## 2. Create Public Hostnames

In Cloudflare, create a remotely managed tunnel named `trotter-home`. Copy its token into `secrets/cloudflare_tunnel_token`, then add two published application routes:

| Public hostname | Service URL |
| --- | --- |
| `api.example.com` | `http://api:8000` |
| `app.example.com` | `http://web:80` |

The service names resolve because `cloudflared`, `api`, and `web` share the Compose network. The tunnel runs from the official `cloudflare/cloudflared` container using its token file.

## 3. Update Google OAuth

In Google Cloud Console, add this authorized redirect URI to the existing OAuth web client:

```text
https://api.example.com/auth/google/callback
```

It must exactly match `TROTTER_API_URL` plus `/auth/google/callback`.

## 4. Move Existing Data

Securely copy `backend/trotter.db` from the development computer to the home server. Keep a separate untouched backup. Before the first full deployment, import it into Postgres:

```bash
cd /opt/trotter/deploy
./scripts/import-sqlite.sh /secure/path/trotter.db
```

The importer refuses a nonempty target database. It copies model tables in dependency order and resets PostgreSQL sequences. Use the exact old encryption key so imported OAuth credentials continue to work.

## 5. Deploy

```bash
cd /opt/trotter/deploy
./scripts/deploy.sh
```

The deployment builds the images, validates production configuration, applies Alembic migrations, and starts all services. API and worker startup waits for healthy Postgres and Redis. Containers use `restart: unless-stopped`, so they return after a server reboot when Docker starts.

Verify locally and publicly:

```bash
curl --fail http://127.0.0.1:8000/ready
curl --fail http://127.0.0.1:8080/health
curl --fail https://api.example.com/ready
curl --fail https://app.example.com/health
docker compose --env-file home-server.env -f compose.yml ps
```

## 6. Build the Native App

The API URL is compiled into standalone Android builds:

```powershell
.\scripts\Build-Android-Artifacts.ps1 -Mode apk -Development -ApiBaseUrl https://api.example.com
```

Release builds require an HTTPS API URL. The web image receives the same URL during its Docker build.

## Operations

View service status and logs:

```bash
docker compose --env-file home-server.env -f compose.yml ps
docker compose --env-file home-server.env -f compose.yml logs -f api worker tunnel
```

Deploy an update:

```bash
git pull --ff-only
cd deploy
./scripts/deploy.sh
```

Create a database backup:

```bash
cd /opt/trotter/deploy
./scripts/backup.sh
```

Backups are written to ignored `deploy/backups/` with SHA-256 files. Copy them to another machine or encrypted backup destination; a backup stored only on the home server does not protect against server or disk loss.

Example daily cron entry:

```cron
15 3 * * * cd /opt/trotter/deploy && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Restore is intentionally guarded because it replaces the current database:

```bash
./scripts/restore.sh /absolute/path/to/trotter.dump --confirm-replace-database
```

## Security Notes

- Keep `DEV_MODE=false`; production preflight refuses to start otherwise.
- API docs are disabled in production.
- CORS only allows the configured web origin.
- Only the API and web applications are routed through Cloudflare. Never publish Postgres, Redis, Docker, SSH, or Ollama through the public tunnel.
- Add Cloudflare rate limits for `/auth/*` and `/ingest/*` after the first successful deployment.
- Rotate the Cloudflare tunnel token if it is exposed. Do not rotate `ENCRYPTION_KEY` without a deliberate refresh-token re-encryption migration.

## Optional Ollama

Dream parsing expects Ollama at `OLLAMA_BASE_URL`, which defaults to `http://host.docker.internal:11434` in this deployment. Install and run Ollama directly on the home server, bind it only to interfaces reachable from Docker, and pull the configured `qwen3.5:4b` model. Do not expose Ollama through Cloudflare.
