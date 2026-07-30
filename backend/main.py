import os
import secrets
import smtplib
from email.mime.text import MIMEText

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

from db import init_db, get_conn, get_state, set_state
import auth
import spotify_client
import sync

app = FastAPI(title="Spotify Curator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your actual frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup():
    init_db()
    scheduler.add_job(sync.run_sync, "interval", hours=4, id="sync_job")
    scheduler.start()


# ---------- Admin: invite + Spotify linking ----------

class InviteRequest(BaseModel):
    email: str


@app.post("/api/admin/invite")
def send_invite(req: InviteRequest, _: bool = Depends(auth.require_admin)):
    token = auth.create_user_token()
    domain = os.environ.get("APP_DOMAIN", "https://yourdomain.com")
    link = f"{domain}/auth?token={token}"

    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ["SMTP_PORT"])
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    msg = MIMEText(f"Here's your playlist curator link:\n\n{link}\n\nThis link is valid for 30 days.")
    msg["Subject"] = "Your playlist curator access link"
    msg["From"] = smtp_user
    msg["To"] = req.email

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [req.email], msg.as_string())

    return {"sent": True}


@app.get("/api/admin/spotify/authorize")
def spotify_authorize(_: bool = Depends(auth.require_admin)):
    """One-time step: visit this as the admin, log in with the Spotify
    account whose Liked Songs should be curated, and approve access."""
    state = secrets.token_urlsafe(16)
    set_state("spotify_oauth_state", state)
    return RedirectResponse(spotify_client.build_authorize_url(state))


@app.get("/api/admin/spotify/callback")
async def spotify_callback(code: str, state: str):
    expected = get_state("spotify_oauth_state")
    if state != expected:
        raise HTTPException(status_code=400, detail="State mismatch")
    await spotify_client.exchange_code_for_tokens(code)
    return {"linked": True}


class TargetPlaylistRequest(BaseModel):
    playlist_id: str


@app.post("/api/admin/target-playlist")
def set_target_playlist(req: TargetPlaylistRequest, _: bool = Depends(auth.require_admin)):
    set_state("target_playlist_id", req.playlist_id)
    return {"ok": True}


# ---------- Admin: read-only views ----------

@app.get("/api/admin/status")
def admin_status(_: bool = Depends(auth.require_admin)):
    return {
        "sync_status": get_state("sync_status", "idle"),
        "sync_paused": get_state("sync_paused", "0") == "1",
        "last_sync_time": get_state("last_sync_time"),
        "target_playlist_id": get_state("target_playlist_id"),
        "spotify_linked": get_state("spotify_refresh_token") is not None,
    }


# ---------- User-facing (magic link) ----------

def _issue_refreshed_header(response, payload):
    refreshed = auth.maybe_refreshed_token(payload)
    if refreshed:
        response.headers["X-Refreshed-Token"] = refreshed


@app.get("/api/state")
def get_app_state(user=Depends(auth.require_user)):
    return {
        "sync_paused": get_state("sync_paused", "0") == "1",
        "last_sync_time": get_state("last_sync_time"),
        "sync_status": get_state("sync_status", "idle"),
    }


@app.post("/api/state/sync-paused")
def set_sync_paused(paused: bool, user=Depends(auth.require_user)):
    set_state("sync_paused", "1" if paused else "0")
    return {"ok": True}


@app.post("/api/sync-now")
async def sync_now(background_tasks: BackgroundTasks, user=Depends(auth.require_user)):
    background_tasks.add_task(sync.run_sync)
    return {"triggered": True}


@app.get("/api/tracks")
def list_tracks(q: str = "", user=Depends(auth.require_user)):
    with get_conn() as conn:
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                """
                SELECT tracks.*, artists.name as artist_name FROM tracks
                LEFT JOIN artists ON tracks.artist_id = artists.id
                WHERE tracks.title LIKE ? OR artists.name LIKE ? OR tracks.album_name LIKE ?
                ORDER BY tracks.added_at DESC
                """,
                (like, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT tracks.*, artists.name as artist_name FROM tracks
                LEFT JOIN artists ON tracks.artist_id = artists.id
                ORDER BY tracks.added_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]


class VisibilityRequest(BaseModel):
    uri: str
    is_hidden: bool


@app.post("/api/tracks/visibility")
def set_track_visibility(req: VisibilityRequest, user=Depends(auth.require_user)):
    with get_conn() as conn:
        conn.execute("UPDATE tracks SET is_hidden = ? WHERE uri = ?", (1 if req.is_hidden else 0, req.uri))
        conn.commit()
    return {"ok": True}


@app.get("/api/rules")
def get_rules(user=Depends(auth.require_user)):
    with get_conn() as conn:
        artists = [dict(r) for r in conn.execute("SELECT * FROM blocked_artists")]
        genres = [r["genre_name"] for r in conn.execute("SELECT * FROM blocked_genres")]
    return {"blocked_artists": artists, "blocked_genres": genres}


class BlockArtistRequest(BaseModel):
    artist_id: str
    name: str


@app.post("/api/rules/blocked-artists")
def add_blocked_artist(req: BlockArtistRequest, user=Depends(auth.require_user)):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO blocked_artists (artist_id, name) VALUES (?, ?)",
            (req.artist_id, req.name),
        )
        conn.commit()
    return {"ok": True}


@app.delete("/api/rules/blocked-artists/{artist_id}")
def remove_blocked_artist(artist_id: str, user=Depends(auth.require_user)):
    with get_conn() as conn:
        conn.execute("DELETE FROM blocked_artists WHERE artist_id = ?", (artist_id,))
        conn.commit()
    return {"ok": True}


class BlockGenreRequest(BaseModel):
    genre_name: str


@app.post("/api/rules/blocked-genres")
def add_blocked_genre(req: BlockGenreRequest, user=Depends(auth.require_user)):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO blocked_genres (genre_name) VALUES (?)", (req.genre_name,))
        conn.commit()
    return {"ok": True}


@app.delete("/api/rules/blocked-genres/{genre_name}")
def remove_blocked_genre(genre_name: str, user=Depends(auth.require_user)):
    with get_conn() as conn:
        conn.execute("DELETE FROM blocked_genres WHERE genre_name = ?", (genre_name,))
        conn.commit()
    return {"ok": True}
