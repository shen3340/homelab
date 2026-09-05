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
API_URL = "https://api.spotify.com/v1"

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
            f"{API_URL}/me/player/devices",
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
            f"{API_URL}/me/player/shuffle",
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
            f"{API_URL}/me/player/repeat",
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
            f"{API_URL}/me/player/play",
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


async def get_album_tracks(
    album_id: str,
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> list[dict]:
    tracks: list[dict] = []
    offset = 0

    while True:
        response = await client.get(
            f"{API_URL}/albums/{album_id}/tracks",
            headers=headers,
            params={
                "market": "US",
                "limit": 50,
                "offset": offset,
            },
        )

        response.raise_for_status()

        data = response.json()
        items = data.get("items", [])

        tracks.extend(items)

        if not data.get("next") or not items:
            break

        offset += len(items)

    return tracks


async def get_album_metadata(
    album: dict,
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> dict:
    album_id = album.get("id")

    if not album_id:
        raise RuntimeError("Spotify album did not contain an ID")

    tracks = await get_album_tracks(
        album_id=album_id,
        client=client,
        headers=headers,
    )

    explicit = any(track.get("explicit", False) for track in tracks)

    artists = album.get("artists", [])

    artist = artists[0].get("name", "") if artists else ""

    release_date = album.get("release_date", "")

    return {
        "spotify_id": album_id,
        "spotify_uri": album.get("uri"),
        "artist": artist,
        "title": album.get("name", ""),
        "release_date": release_date,
        "release_year": release_date[:4] if release_date else None,
        "album_type": album.get("album_type"),
        "total_tracks": album.get("total_tracks", len(tracks)),
        "explicit": explicit,
        "image_url": (
            album.get("images", [{}])[0].get("url") if album.get("images") else None
        ),
    }


async def get_album_by_id(album_id: str) -> dict | None:
    token = await get_valid_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_URL}/albums/{album_id}",
            headers=headers,
            params={"market": "US"},
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        album = response.json()

        try:
            return await get_album_metadata(
                album=album,
                client=client,
                headers=headers,
            )
        except (httpx.HTTPError, RuntimeError):
            return None


async def search_albums(query: str) -> list[dict]:
    token = await get_valid_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
    }

    params = {
        "q": query,
        "type": "album",
        "limit": 10,
        "market": "US",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_URL}/search",
            headers=headers,
            params=params,
        )

        response.raise_for_status()

        data = response.json()

        albums = data.get("albums", {}).get("items", [])

        results = []

        for album in albums:
            try:
                metadata = await get_album_metadata(
                    album=album,
                    client=client,
                    headers=headers,
                )
            except (httpx.HTTPError, RuntimeError):
                continue

            results.append(metadata)

    # Explicit releases first.
    results.sort(
        key=lambda album: (
            not album["explicit"],
            album["artist"].lower(),
            album["title"].lower(),
        )
    )

    return results


async def search_album(artist: str, title: str) -> dict | None:
    query = f'album:"{title}" artist:"{artist}"'

    results = await search_albums(query)

    exact_matches = [
        album
        for album in results
        if (
            album["title"].strip().lower() == title.strip().lower()
            and album["artist"].strip().lower() == artist.strip().lower()
        )
    ]

    if not exact_matches:
        return None

    return exact_matches[0]
