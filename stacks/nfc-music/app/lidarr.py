import os
import re
import unicodedata

import httpx

LIDARR_URL = os.getenv("LIDARR_URL", "").rstrip("/")
LIDARR_API_KEY = os.getenv("LIDARR_API_KEY", "")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    return re.sub(r"[^a-z0-9]", "", value)


async def get_library_tracks() -> list[dict]:
    if not LIDARR_URL or not LIDARR_API_KEY:
        raise RuntimeError("Lidarr configuration is missing")

    headers = {"X-Api-Key": LIDARR_API_KEY}

    async with httpx.AsyncClient(timeout=60) as client:
        artists_response = await client.get(
            f"{LIDARR_URL}/api/v1/artist",
            headers=headers,
        )
        artists_response.raise_for_status()

        artists = artists_response.json()
        tracks = []

        for artist in artists:
            tracks_response = await client.get(
                f"{LIDARR_URL}/api/v1/track",
                headers=headers,
                params={"artistId": artist["id"]},
            )
            tracks_response.raise_for_status()

            for track in tracks_response.json():
                tracks.append(
                    {
                        "title": track["title"],
                        "artist": artist["artistName"],
                        "has_file": track.get("trackFileId") is not None,
                        "track_file_id": track.get("trackFileId"),
                    }
                )

    return tracks


def compare_tracks(
    spotify_tracks: list[dict],
    lidarr_tracks: list[dict],
) -> list[dict]:
    indexed = {}

    for track in lidarr_tracks:
        key = (
            normalize(track["title"]),
            normalize(track["artist"]),
        )
        indexed.setdefault(key, []).append(track)

    results = []

    for track in spotify_tracks:
        key = (
            normalize(track["title"]),
            normalize(track["artist"]),
        )

        matches = indexed.get(key, [])

        if not matches:
            status = "not_in_lidarr"
        elif any(match["has_file"] for match in matches):
            status = "on_nas"
        else:
            status = "missing_file"

        results.append(
            {
                **track,
                "status": status,
            }
        )

    return results
