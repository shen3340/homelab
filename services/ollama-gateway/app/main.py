import asyncio
import os
import socket
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse


PRIMARY_OLLAMA = os.getenv(
    "PRIMARY_OLLAMA",
).rstrip("/")

BACKUP_OLLAMA = os.getenv(
    "BACKUP_OLLAMA"
).rstrip("/")

BACKUP_MAC = os.getenv(
    "BACKUP_MAC",
)

WOL_BROADCAST = os.getenv(
    "WOL_BROADCAST",
)

WOL_PORT = int(
    os.getenv(
        "WOL_PORT",
        "9",
    )
)

PRIMARY_HEALTH_TIMEOUT = float(
    os.getenv(
        "PRIMARY_HEALTH_TIMEOUT",
        "3",
    )
)

BACKUP_HEALTH_TIMEOUT = float(
    os.getenv(
        "BACKUP_HEALTH_TIMEOUT",
        "3",
    )
)

BACKUP_STARTUP_TIMEOUT = float(
    os.getenv(
        "BACKUP_STARTUP_TIMEOUT",
        "120",
    )
)

BACKUP_POLL_INTERVAL = float(
    os.getenv(
        "BACKUP_POLL_INTERVAL",
        "2",
    )
)

WOL_COOLDOWN = float(
    os.getenv(
        "WOL_COOLDOWN",
        "60",
    )
)


client: httpx.AsyncClient | None = None

last_wol_time = 0.0

startup_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=10.0,
            read=None,
            write=None,
            pool=None,
        ),
        follow_redirects=True,
    )

    yield

    await client.aclose()


app = FastAPI(
    title="Ollama Failover Gateway",
    lifespan=lifespan,
)


def get_client() -> httpx.AsyncClient:
    if client is None:
        raise RuntimeError("HTTP client not initialized")

    return client


async def ollama_health(
    base_url: str,
    timeout: float,
) -> bool:
    try:
        response = await get_client().get(
            f"{base_url}/api/tags",
            timeout=timeout,
        )

        return response.is_success

    except (
        httpx.HTTPError,
        asyncio.TimeoutError,
    ):
        return False


def send_wol() -> None:
    mac = BACKUP_MAC.replace(":", "").replace("-", "")

    if len(mac) != 12:
        raise ValueError(
            f"Invalid MAC address: {BACKUP_MAC}"
        )

    try:
        mac_bytes = bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError(
            f"Invalid MAC address: {BACKUP_MAC}"
        ) from exc

    packet = (
        b"\xff" * 6
        + mac_bytes * 16
    )

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )

    try:
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_BROADCAST,
            1,
        )

        sock.sendto(
            packet,
            (
                WOL_BROADCAST,
                WOL_PORT,
            ),
        )

    finally:
        sock.close()


async def wake_backup() -> None:
    global last_wol_time

    async with startup_lock:

        # Someone else may have started the backup while
        # this request was waiting for the lock.
        if await ollama_health(
            BACKUP_OLLAMA,
            BACKUP_HEALTH_TIMEOUT,
        ):
            return

        now = time.monotonic()

        if (
            now - last_wol_time
            >= WOL_COOLDOWN
        ):
            print(
                "Backup unavailable. Sending Wake-on-LAN."
            )

            send_wol()

            last_wol_time = now

        else:
            print(
                "Backup unavailable, but WoL cooldown active."
            )

        deadline = (
            time.monotonic()
            + BACKUP_STARTUP_TIMEOUT
        )

        while time.monotonic() < deadline:

            if await ollama_health(
                BACKUP_OLLAMA,
                BACKUP_HEALTH_TIMEOUT,
            ):
                print(
                    "Backup Ollama is ready."
                )

                return

            await asyncio.sleep(
                BACKUP_POLL_INTERVAL
            )

        raise RuntimeError(
            "Backup Ollama did not become available "
            f"within {BACKUP_STARTUP_TIMEOUT} seconds."
        )


async def select_backend() -> str:
    # Primary always gets preference.
    if await ollama_health(
        PRIMARY_OLLAMA,
        PRIMARY_HEALTH_TIMEOUT,
    ):
        return PRIMARY_OLLAMA

    print(
        "Primary Ollama unavailable."
    )

    # Backup is already awake.
    if await ollama_health(
        BACKUP_OLLAMA,
        BACKUP_HEALTH_TIMEOUT,
    ):
        print(
            "Using backup Ollama."
        )

        return BACKUP_OLLAMA

    # Backup needs to be awakened.
    print(
        "Backup Ollama unavailable. "
        "Attempting Wake-on-LAN."
    )

    await wake_backup()

    return BACKUP_OLLAMA


def filter_request_headers(
    headers: httpx.Headers,
) -> dict[str, str]:
    excluded = {
        "host",
        "content-length",
    }

    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in excluded
    }


def filter_response_headers(
    headers: httpx.Headers,
) -> dict[str, str]:
    excluded = {
        "content-length",
        "transfer-encoding",
        "connection",
    }

    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in excluded
    }


@app.get("/health")
async def gateway_health():
    primary = await ollama_health(
        PRIMARY_OLLAMA,
        PRIMARY_HEALTH_TIMEOUT,
    )

    backup = await ollama_health(
        BACKUP_OLLAMA,
        BACKUP_HEALTH_TIMEOUT,
    )

    return {
        "status": "ok",
        "primary": primary,
        "backup": backup,
    }


@app.get("/backend")
async def backend_status():
    primary = await ollama_health(
        PRIMARY_OLLAMA,
        PRIMARY_HEALTH_TIMEOUT,
    )

    if primary:
        return {
            "backend": "primary",
            "url": PRIMARY_OLLAMA,
        }

    backup = await ollama_health(
        BACKUP_OLLAMA,
        BACKUP_HEALTH_TIMEOUT,
    )

    if backup:
        return {
            "backend": "backup",
            "url": BACKUP_OLLAMA,
        }

    return {
        "backend": "offline",
    }


@app.api_route(
    "/{path:path}",
    methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "HEAD",
        "OPTIONS",
    ],
)
async def proxy(
    path: str,
    request: Request,
):
    backend = await select_backend()

    url = f"{backend}/{path}"

    if request.url.query:
        url += f"?{request.url.query}"

    body = await request.body()

    headers = filter_request_headers(
        request.headers
    )

    try:
        upstream_request = get_client().build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )

        upstream_response = await get_client().send(
            upstream_request,
            stream=True,
        )

    except httpx.HTTPError as exc:

        # If primary died after health check,
        # retry the request through backup.

        if backend == PRIMARY_OLLAMA:

            print(
                "Primary request failed. "
                "Failing over to backup."
            )

            await wake_backup()

            backend = BACKUP_OLLAMA

            url = f"{backend}/{path}"

            if request.url.query:
                url += f"?{request.url.query}"

            upstream_request = get_client().build_request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )

            try:
                upstream_response = await get_client().send(
                    upstream_request,
                    stream=True,
                )

            except httpx.HTTPError as backup_exc:
                raise Response(
                    content=str(backup_exc),
                    status_code=502,
                )

        else:
            raise Response(
                content=str(exc),
                status_code=502,
            )

    async def stream_response() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream_response.aiter_raw():
                yield chunk

        finally:
            await upstream_response.aclose()

    return StreamingResponse(
        stream_response(),
        status_code=upstream_response.status_code,
        headers=filter_response_headers(
            upstream_response.headers
        ),
        media_type=upstream_response.headers.get(
            "content-type"
        ),
    )