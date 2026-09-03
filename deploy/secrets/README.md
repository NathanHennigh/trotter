# Home-server secrets

Create these extensionless files in this directory before deployment:

- `postgres_password`: a new random database password.
- `jwt_secret`: at least 32 random characters.
- `encryption_key`: the existing backend `ENCRYPTION_KEY` when migrating data. Changing it makes stored Google refresh tokens unreadable.
- `google_client_secret`: the existing Google OAuth web client secret.
- `cloudflare_tunnel_token`: the token for the remotely managed Cloudflare Tunnel.

Run `./scripts/init-secrets.sh` on the Linux server to generate the first two and a new encryption key. When migrating the existing database, replace the generated encryption key with the exact value from the current backend `.env` before importing data.

These files are ignored by Git. Restrict the directory and files to the deployment user (`chmod 700 secrets && chmod 600 secrets/*`).
