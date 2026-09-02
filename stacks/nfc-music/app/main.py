from fastapi import FastAPI, HTTPException

from app.database import get_connection, get_tag

app = FastAPI(
    title="NFC Music",
    version="0.1.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "nfc-music",
        "status": "ok",
    }


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
