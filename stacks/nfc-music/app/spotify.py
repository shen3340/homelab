import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.database import (
    get_spotify_tokens,
    save_spotify_tokens,
    update_spotify_access_token,
)

CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REDIRECT_URI = os.environ["SPOTIFY_REDIRECT_URI"]

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
]


def get_authorization_url(state: str) -> str:
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
    }

    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )

        response.raise_for_status()

        return response.json()


def calculate_expires_at(expires_in: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def save_token_response(tokens: dict) -> None:
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens["expires_in"]

    if not refresh_token:
        raise RuntimeError(
            "Spotify authorization response did not contain a refresh token"
        )

    expires_at = calculate_expires_at(expires_in)

    save_spotify_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )

        response.raise_for_status()

        return response.json()


async def get_valid_access_token() -> str:
    tokens = get_spotify_tokens()

    if tokens is None:
        raise RuntimeError("Spotify authorization is required")

    now = datetime.now(timezone.utc)

    # Refresh slightly before expiration so an API request does not
    # start with a token that expires during the request.
    refresh_threshold = now + timedelta(seconds=60)

    if tokens["expires_at"] > refresh_threshold:
        return tokens["access_token"]

    refreshed = await refresh_access_token(tokens["refresh_token"])

    access_token = refreshed["access_token"]
    expires_at = calculate_expires_at(refreshed["expires_in"])

    update_spotify_access_token(
        access_token=access_token,
        expires_at=expires_at,
        refresh_token=refreshed.get("refresh_token"),
    )

    return access_token


async def get_devices() -> list[dict]:
    access_token = await get_valid_access_token()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.spotify.com/v1/me/player/devices",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
        )

        response.raise_for_status()

        return response.json()["devices"]


async def set_shuffle(
    state: bool,
    device_id: str,
) -> None:
    access_token = await get_valid_access_token()

    async with httpx.AsyncClient() as client:
        response = await client.put(
            "https://api.spotify.com/v1/me/player/shuffle",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            params={
                "state": str(state).lower(),
                "device_id": device_id,
            },
        )

        response.raise_for_status()


async def set_repeat(
    state: str,
    device_id: str,
) -> None:
    access_token = await get_valid_access_token()

    async with httpx.AsyncClient() as client:
        response = await client.put(
            "https://api.spotify.com/v1/me/player/repeat",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            params={
                "state": state,
                "device_id": device_id,
            },
        )

        response.raise_for_status()


async def start_album(
    album_uri: str,
    device_id: str,
) -> None:
    access_token = await get_valid_access_token()

    async with httpx.AsyncClient() as client:
        response = await client.put(
            "https://api.spotify.com/v1/me/player/play",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={
                "device_id": device_id,
            },
            json={
                "context_uri": album_uri,
                "position_ms": 0,
            },
        )

        response.raise_for_status()


async def search_album(artist: str, title: str) -> dict | None:
    token = await get_valid_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
    }

    params = {
        "q": f'album:"{title}" artist:"{artist}"',
        "type": "album",
        "limit": 10,
        "market": "US",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params=params,
        )
        response.raise_for_status()

        data = response.json()

        albums = data.get("albums", {}).get("items", [])

        candidates = []

        for album in albums:
            album_title = album.get("name", "").strip()
            album_artists = [
                a.get("name", "").strip() for a in album.get("artists", [])
            ]

            if album_title.lower() != title.strip().lower():
                continue

            if artist.strip().lower() not in {a.lower() for a in album_artists}:
                continue

            candidates.append(album)

        if not candidates:
            return None

        # Check each matching album for explicit tracks.
        explicit_candidates = []

        for album in candidates:
            album_id = album.get("id")

            if not album_id:
                continue

            tracks_response = await client.get(
                f"https://api.spotify.com/v1/albums/{album_id}/tracks",
                headers=headers,
                params={
                    "market": "US",
                    "limit": 50,
                },
            )
            tracks_response.raise_for_status()

            tracks = tracks_response.json().get("items", [])

            if any(track.get("explicit", False) for track in tracks):
                explicit_candidates.append(album)

        # Prefer an explicit release when one exists.
        if explicit_candidates:
            candidates = explicit_candidates

        selected = candidates[0]

        selected_artist = selected.get("artists", [{}])[0].get("name", artist)

        return {
            "artist": selected_artist,
            "title": selected.get("name", title),
            "spotify_uri": selected.get("uri"),
        }
