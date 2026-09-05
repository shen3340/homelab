import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg.errors import UniqueViolation
from pydantic import BaseModel

from app.database import (
    consume_oauth_state,
    create_album,
    create_tag,
    delete_album,
    delete_tag,
    get_album_by_spotify_id,
    get_all_albums,
    get_all_tags,
    get_connection,
    get_spotify_device,
    get_tag,
    initialize_auth_tables,
    save_oauth_state,
    update_album,
    update_tag,
)

from app.spotify import (
    exchange_code,
    get_album_by_id,
    get_authorization_url,
    get_devices,
    save_token_response,
    search_albums,
    set_repeat,
    set_shuffle,
    start_album,
)


class AlbumCreate(BaseModel):
    spotify_id: str
    navidrome_id: str | None = None


class AlbumUpdate(BaseModel):
    artist: str
    title: str
    spotify_uri: str | None = None
    navidrome_id: str | None = None


class TagCreate(BaseModel):
    tag_uid: str
    album_id: int


class TagUpdate(BaseModel):
    tag_uid: str
    album_id: int
    enabled: bool


app = FastAPI(
    title="NFC Music",
    version="0.1.0",
)

BASE_DIR = Path(__file__).resolve().parent

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates",
)


@app.on_event("startup")
def startup() -> None:
    initialize_auth_tables()


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "healthy",
    }


@app.get("/health/db")
async def database_health() -> dict[str, str]:
    with get_connection() as connection:
        connection.execute("SELECT 1")

    return {
        "status": "healthy",
        "database": "connected",
    }


@app.get("/tags/{tag_uid}")
async def tag_lookup(tag_uid: str) -> dict:
    tag = get_tag(tag_uid)

    if tag is None:
        raise HTTPException(
            status_code=404,
            detail="Tag not found",
        )

    return tag


@app.get("/auth/login")
async def spotify_login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    save_oauth_state(
        state=state,
        expires_at=expires_at,
    )

    authorization_url = get_authorization_url(state)

    return RedirectResponse(authorization_url)


@app.get("/auth/callback")
async def spotify_callback(
    code: str,
    state: str,
) -> dict[str, str | int]:
    if not consume_oauth_state(state):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state",
        )

    tokens = await exchange_code(code)

    save_token_response(tokens)

    return {
        "status": "authorized",
        "token_type": tokens["token_type"],
        "expires_in": tokens["expires_in"],
        "scope": tokens["scope"],
    }


@app.get("/t/{tag_uid}", response_class=HTMLResponse)
async def nfc_tag(tag_uid: str) -> str:
    tag = get_tag(tag_uid)

    if tag is None:
        raise HTTPException(
            status_code=404,
            detail="Tag not found",
        )

    album_uri = tag["spotify_uri"]

    if not album_uri:
        raise HTTPException(
            status_code=400,
            detail="Tag does not have a Spotify album URI",
        )

    if not album_uri.startswith("spotify:album:"):
        raise HTTPException(
            status_code=400,
            detail="Tag Spotify URI is not an album URI",
        )

    devices = await get_devices()

    if not devices:
        raise HTTPException(
            status_code=400,
            detail="No Spotify devices available",
        )

    preferred_device = get_spotify_device()

    device = None

    if preferred_device is not None:
        device = next(
            (
                candidate
                for candidate in devices
                if candidate["id"] == preferred_device["device_id"]
            ),
            None,
        )

    if device is None:
        active_devices = [candidate for candidate in devices if candidate["is_active"]]

        if active_devices:
            device = active_devices[0]
        else:
            device = devices[0]

    device_id = device["id"]

    await set_shuffle(
        state=False,
        device_id=device_id,
    )

    await set_repeat(
        state="off",
        device_id=device_id,
    )

    await start_album(
        album_uri=album_uri,
        device_id=device_id,
    )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>NFC Music</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>
    <body>
        <h1>Now Playing</h1>
        <p>{tag["artist"]} — {tag["title"]}</p>
        <p>Playing on {device["name"]}</p>
    </body>
    </html>
    """


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "static_version": int(datetime.now().timestamp()),
        },
    )


@app.get("/admin/spotify/search")
async def admin_search_spotify(q: str) -> list[dict]:
    query = q.strip()

    if not query:
        return []

    try:
        return await search_albums(query)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Spotify search failed.",
        )


@app.get("/admin/tags")
async def admin_get_tags() -> list[dict]:
    return get_all_tags()


@app.post("/admin/albums")
async def admin_create_album(album: AlbumCreate) -> dict:
    spotify_album = await get_album_by_id(album.spotify_id)

    if spotify_album is None:
        raise HTTPException(
            status_code=404,
            detail="Album not found on Spotify",
        )

    existing = get_album_by_spotify_id(album.spotify_id)

    if existing is not None:
        return existing

    album_id = create_album(
        artist=spotify_album["artist"],
        title=spotify_album["title"],
        spotify_id=spotify_album["spotify_id"],
        spotify_uri=spotify_album["spotify_uri"],
        navidrome_id=album.navidrome_id,
    )

    return {
        "id": album_id,
        "artist": spotify_album["artist"],
        "title": spotify_album["title"],
        "spotify_id": spotify_album["spotify_id"],
        "spotify_uri": spotify_album["spotify_uri"],
        "navidrome_id": album.navidrome_id,
    }


@app.post("/admin/tags")
async def admin_create_tag(tag: TagCreate) -> dict:
    try:
        tag_id = create_tag(
            tag_uid=tag.tag_uid,
            album_id=tag.album_id,
        )
    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="This NFC tag is already registered.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    return {
        "id": tag_id,
        "tag_uid": tag.tag_uid,
        "album_id": tag.album_id,
    }


@app.put("/admin/tags/{tag_id}")
async def admin_update_tag(
    tag_id: int,
    tag: TagUpdate,
) -> dict:
    try:
        update_tag(
            tag_id=tag_id,
            tag_uid=tag.tag_uid,
            album_id=tag.album_id,
            enabled=tag.enabled,
        )
    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="This NFC tag is already registered.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    return {
        "id": tag_id,
        "tag_uid": tag.tag_uid,
        "album_id": tag.album_id,
        "enabled": tag.enabled,
    }


@app.delete("/admin/tags/{tag_id}")
async def admin_delete_tag(tag_id: int) -> dict:
    deleted = delete_tag(tag_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Tag not found",
        )

    return {
        "status": "deleted",
        "id": tag_id,
    }


@app.get("/admin/albums")
async def admin_get_albums() -> list[dict]:
    return get_all_albums()


@app.put("/admin/albums/{album_id}")
async def admin_update_album(
    album_id: int,
    album: AlbumUpdate,
) -> dict:
    updated = update_album(
        album_id=album_id,
        artist=album.artist,
        title=album.title,
        spotify_uri=album.spotify_uri,
        navidrome_id=album.navidrome_id,
    )

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Album not found",
        )

    return {
        "status": "updated",
        "id": album_id,
    }


@app.delete("/admin/albums/{album_id}")
async def admin_delete_album(album_id: int) -> dict:
    deleted = delete_album(album_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Album not found",
        )

    return {
        "status": "deleted",
        "id": album_id,
    }
