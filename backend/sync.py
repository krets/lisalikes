import time
import json
import logging

from db import get_conn, get_state, set_state
import spotify_client

logger = logging.getLogger("sync")


async def run_sync():
    if get_state("sync_paused", "0") == "1":
        logger.info("Sync is paused, skipping run")
        return

    set_state("sync_status", "syncing")
    set_state("last_sync_error", "")

    try:
        await _ingest()
        set_state("last_ingest_time", int(time.time()))
    except Exception as e:
        set_state("sync_status", "error")
        set_state("last_sync_error", f"Loading Liked Songs failed: {e}")
        logger.exception("Ingest failed")
        raise

    playlist_id = get_state("target_playlist_id")
    if not playlist_id:
        set_state("sync_status", "idle")
        set_state("last_sync_error", "No target playlist is set, so nothing was published.")
        return

    uris = _curate()
    try:
        if uris:
            await spotify_client.publish_playlist(playlist_id, uris)
        set_state("last_publish_time", int(time.time()))
        set_state("sync_status", "idle")
    except Exception as e:
        set_state("sync_status", "error")
        set_state("last_sync_error", f"Publishing to the playlist failed: {e}")
        logger.exception("Publish failed")
        raise


async def _ingest():
    items = await spotify_client.fetch_all_liked_tracks()

    with get_conn() as conn:
        artist_ids_seen = set()
        for item in items:
            track = item["track"]
            artist = track["artists"][0] if track["artists"] else None
            artist_id = artist["id"] if artist else None
            image_url = None
            if track["album"]["images"]:
                # smallest image is last in the list; Spotify's smallest is usually 64x64
                image_url = track["album"]["images"][-1]["url"]

            conn.execute(
                """
                INSERT INTO tracks (uri, title, album_name, image_url, artist_id, added_at, duration_ms, is_hidden)
                VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT is_hidden FROM tracks WHERE uri = ?), 0))
                ON CONFLICT(uri) DO UPDATE SET
                    title = excluded.title,
                    album_name = excluded.album_name,
                    image_url = excluded.image_url,
                    artist_id = excluded.artist_id,
                    added_at = excluded.added_at,
                    duration_ms = excluded.duration_ms
                """,
                (
                    track["uri"],
                    track["name"],
                    track["album"]["name"],
                    image_url,
                    artist_id,
                    item["added_at"],
                    track.get("duration_ms"),
                    track["uri"],
                ),
            )
            if artist_id:
                artist_ids_seen.add(artist_id)
        conn.commit()

        existing = {
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM artists WHERE id IN ({','.join('?' * len(artist_ids_seen))})",
                tuple(artist_ids_seen),
            )
        } if artist_ids_seen else set()
        new_artist_ids = list(artist_ids_seen - existing)

    if new_artist_ids:
        artists = await spotify_client.fetch_artists(new_artist_ids)
        with get_conn() as conn:
            for a in artists:
                conn.execute(
                    "INSERT INTO artists (id, name, genres) VALUES (?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET name = excluded.name, genres = excluded.genres",
                    (a["id"], a["name"], json.dumps(a.get("genres", []))),
                )
            conn.commit()


def _curate() -> list[str]:
    with get_conn() as conn:
        blocked_genres = [r["genre_name"] for r in conn.execute("SELECT genre_name FROM blocked_genres")]
        rows = conn.execute(
            """
            SELECT tracks.uri, artists.genres FROM tracks
            LEFT JOIN artists ON tracks.artist_id = artists.id
            WHERE tracks.is_hidden = 0
              AND tracks.artist_id NOT IN (SELECT artist_id FROM blocked_artists)
            ORDER BY tracks.added_at DESC
            """
        ).fetchall()

    uris = []
    for row in rows:
        genres = json.loads(row["genres"]) if row["genres"] else []
        if any(g in genres for g in blocked_genres):
            continue
        uris.append(row["uri"])
    return uris
