/**
 * src/api/config.js
 * ─────────────────────────────────────────────────────────────────
 * SETUP INSTRUCTIONS
 *
 * When running on a physical device via Expo Go, localhost won't work.
 * You need a public URL for the backend. Two options:
 *
 * Option A — ngrok (easiest for dev):
 *   1. npm install -g ngrok
 *   2. Start your FastAPI backend:  cd backend && uvicorn app.main:app --reload
 *   3. In another terminal:        ngrok http 8000
 *   4. Copy the https://xxxx.ngrok-free.app URL below
 *   5. Also set BACKEND_URL=https://xxxx.ngrok-free.app in backend/.env
 *
 * Option B — same LAN (Android only, not OAuth-safe):
 *   Set to your machine's local IP: http://192.168.1.42:8000
 *   (Google OAuth callback won't work with a local IP — use ngrok for auth)
 * ─────────────────────────────────────────────────────────────────
 */
export const BASE_URL = 'https://affectionate-aeroscopically-rhys.ngrok-free.dev';
