# Spotify Curator

Private web app: syncs a Spotify account's Liked Songs every 4 hours, lets
one person (accessed via a magic link, no password) hide tracks and block
artists/genres, and republishes the filtered list to a target playlist.

## 1. Spotify app setup
1. Create an app at https://developer.spotify.com/dashboard.
2. Add a Redirect URI matching `SPOTIFY_REDIRECT_URI` in `.env`
   (`https://yourdomain.com/api/admin/spotify/callback`).
3. Copy the Client ID / Secret into `.env`.

## 2. Configure
```bash
cp .env.example .env
openssl rand -hex 32   # run twice, once for JWT_SECRET, once for ADMIN_SECRET
```
Fill in `.env`: Spotify credentials, your domain, and SMTP creds for sending
the magic link email (Gmail app password, SendGrid, Postmark, etc. all work).

## 3. Run
```bash
docker compose up -d --build
```
Backend on :8000, frontend on :8080. Put a reverse proxy (Caddy/nginx/Traefik)
with TLS in front of it if this is reachable from the internet — the compose
file itself doesn't terminate HTTPS.

## 4. One-time linking
1. Visit `https://yourdomain.com/api/admin/spotify/authorize?secret=<ADMIN_SECRET>`
   and log in with the Spotify account whose Liked Songs you want to curate.
   This stores a refresh token server-side — nobody else needs to do this again.
2. Create the target playlist in Spotify (or reuse one), grab its ID from the
   share link, and set it:
   ```bash
   curl -X POST "https://yourdomain.com/api/admin/target-playlist?secret=<ADMIN_SECRET>" \
     -H "Content-Type: application/json" \
     -d '{"playlist_id": "<PLAYLIST_ID>"}'
   ```
3. Send her the magic link:
   ```bash
   curl -X POST "https://yourdomain.com/api/admin/invite?secret=<ADMIN_SECRET>" \
     -H "Content-Type: application/json" \
     -d '{"email": "her@email.com"}'
   ```
   She clicks the link once; the frontend stores the token and keeps
   refreshing it automatically as long as she visits within 30 days.

## Notes / deviations from the original spec
- **Playlist endpoints**: Spotify's real API uses `PUT/POST
  /v1/playlists/{id}/tracks`, not `/items` — implemented against the actual
  endpoint.
- **Genre matching**: implemented as an exact match against each artist's
  genre list (parsed JSON) rather than a raw substring `instr()` check, to
  avoid accidental partial matches (e.g. "pop" matching "k-pop").
- **Admin secret in the URL**: works as specified, but query-string secrets
  land in server access logs and browser history. Fine for a small
  self-hosted tool behind your own VPS; if you ever put this behind a shared
  proxy or expose it further, switch `require_admin` in `auth.py` to read an
  `X-Admin-Secret` header instead.
- **CORS**: currently wide open (`allow_origins=["*"]`) for ease of local
  dev — tighten to your actual frontend origin before going live.
- Local dev without Docker: `cd backend && uvicorn main:app --reload`,
  `cd frontend && npm install && npm run dev`.
