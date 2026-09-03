# Trotter on Oracle Cloud Always Free

This is the recommended persistent testing deployment. It uses one Oracle Cloud
Ampere A1 VM and the same Compose stack documented in `README.md`. All container
images support `linux/arm64`; Trotter builds PostGIS from the official
multi-architecture PostgreSQL image because the upstream `postgis/postgis` tag is
AMD64-only.

## 1. Create the VM

Create an Always Free-eligible compute instance with:

- Shape: `VM.Standard.A1.Flex`
- CPU and memory: 2 OCPUs and 12 GB RAM
- Image: Ubuntu 24.04 (`aarch64`)
- Boot volume: 50 GB
- Authentication: upload a dedicated SSH public key

Keep the default SSH ingress rule while provisioning. Trotter's HTTP services do
not need public ingress because Cloudflare Tunnel makes outbound connections.
After setup, restrict SSH ingress to trusted source addresses or use Oracle Cloud
Shell/Bastion.

## 2. Prepare the Host

Connect as the image's `ubuntu` user, clone Trotter under the persistent home
directory, and bootstrap Docker:

```bash
git clone https://github.com/NathanHennigh/trotter.git ~/trotter
cd ~/trotter/deploy
chmod +x scripts/*.sh
./scripts/bootstrap-oci.sh
```

If Docker was newly installed, sign out and reconnect once so group membership is
applied, then rerun `./scripts/bootstrap-oci.sh`.

## 3. Configure Trotter

Follow `deploy/README.md`, using the OCI VM instead of `/opt/trotter`:

```bash
cd ~/trotter/deploy
cp home-server.env.example home-server.env
./scripts/init-secrets.sh
```

Set `TROTTER_API_URL`, `TROTTER_API_HOST`, `TROTTER_WEB_URL`, and
`GOOGLE_CLIENT_ID`. Copy the existing Google secret and exact encryption key into
the ignored secret files. Create a remotely managed Cloudflare Tunnel and route:

- API hostname to `http://api:8000`
- Web hostname to `http://web:80`

Copy the tunnel token to `deploy/secrets/cloudflare_tunnel_token`.

## 4. Import and Deploy

Copy `backend/trotter.db` to the VM without committing it to Git, then run:

```bash
cd ~/trotter/deploy
./scripts/import-sqlite.sh ~/trotter.db
./scripts/deploy.sh
```

Verify both public URLs and configure the Google OAuth callback as described in
`deploy/README.md`.

## 5. Operate

The Compose services use `restart: unless-stopped` and Docker starts at boot.
Use the existing backup script and copy its output away from the VM:

```bash
cd ~/trotter/deploy
./scripts/backup.sh
docker compose --env-file home-server.env -f compose.yml ps
```

Oracle may reclaim idle Always Free instances. Keep current database backups on a
second system and verify the public `/ready` endpoint periodically.
