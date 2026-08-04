import os
import time
import asyncio
import httpx

from db import get_state, set_state

CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "https://yourdomain.com/api/admin/spotify/callback")

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = "user-library-read playlist-modify-public playlist-modify-private"


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    return f"{AUTH_URL}?{query}"


async def exchange_code_for_tokens(code: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            auth=(CLIENT_ID, CLIENT_SECRET),
        )
        resp.raise_for_status()
        data = resp.json()
        set_state("spotify_refresh_token", data["refresh_token"])
        set_state("spotify_access_token", data["access_token"])
        set_state("spotify_access_token_expires_at", int(time.time()) + data["expires_in"])
        set_state("spotify_granted_scope", data.get("scope", ""))
        return data


async def get_valid_access_token() -> str:
    expires_at = int(get_state("spotify_access_token_expires_at", 0))
    if expires_at - int(time.time()) > 60:
        return get_state("spotify_access_token")

    refresh_token = get_state("spotify_refresh_token")
    if not refresh_token:
        raise RuntimeError("No Spotify refresh token on file. Run the admin Spotify authorize flow first.")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(CLIENT_ID, CLIENT_SECRET),
        )
        resp.raise_for_status()
        data = resp.json()
        set_state("spotify_access_token", data["access_token"])
        set_state("spotify_access_token_expires_at", int(time.time()) + data["expires_in"])
        if "scope" in data:
            set_state("spotify_granted_scope", data["scope"])
        # Spotify sometimes rotates the refresh token
        if "refresh_token" in data:
            set_state("spotify_refresh_token", data["refresh_token"])
        return data["access_token"]


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    token = await get_valid_access_token()
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp


async def fetch_all_liked_tracks() -> list[dict]:
    tracks = []
    offset = 0
    limit = 50
    while True:
        resp = await _request("GET", "/me/tracks", params={"limit": limit, "offset": offset})
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break
        tracks.extend(items)
        offset += limit
        if len(items) < limit:
            break
    return tracks


async def fetch_artists(artist_ids: list[str]) -> list[dict]:
    # Spotify's batched "Several Artists" endpoint (GET /artists?ids=...) returns
    # 403 for apps in Development Mode without Extended Quota approval. The
    # singular endpoint is still reachable, so fetch one at a time instead.
    artists = []
    for artist_id in artist_ids:
        resp = await _request("GET", f"/artists/{artist_id}")
        artists.append(resp.json())
    return artists


async def fetch_playlist_name(playlist_id: str) -> str:
    resp = await _request("GET", f"/playlists/{playlist_id}", params={"fields": "name"})
    return resp.json()["name"]


async def publish_playlist(playlist_id: str, uris: list[str]):
    first_batch, rest = uris[:100], uris[100:]

    await _request(
        "PUT",
        f"/playlists/{playlist_id}/tracks",
        json={"uris": first_batch},
    )

    for i in range(0, len(rest), 100):
        chunk = rest[i : i + 100]
        await _request(
            "POST",
            f"/playlists/{playlist_id}/tracks",
            json={"uris": chunk},
        )
