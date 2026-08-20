import asyncio
import os
import socket
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


# ============================================================
# Configuration
# ============================================================

PRIMARY_OLLAMA = os.getenv(
    "PRIMARY_OLLAMA",
).rstrip("/")

BACKUP_OLLAMA = os.getenv(
    "BACKUP_OLLAMA",
).rstrip("/")

PRIMARY_MAC = os.getenv(
    "PRIMARY_MAC",
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

PRIMARY_RECOVERY_INTERVAL = float(
    os.getenv(
        "PRIMARY_RECOVERY_INTERVAL",
        "5",
    )
)

WOL_COOLDOWN = float(
    os.getenv(
        "WOL_COOLDOWN",
        "60",
    )
)


# ============================================================
# Global state
# ============================================================

client: httpx.AsyncClient | None = None

primary_available = False

primary_recovery_task: asyncio.Task | None = None

last_wol_time = 0.0

state_lock = asyncio.Lock()


# ============================================================
# Application lifecycle
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    global primary_recovery_task

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=10.0,
            read=None,
            write=None,
            pool=None,
        ),
        follow_redirects=True,
    )

    # Determine initial primary state.
    await update_primary_state()

    # Start background recovery monitor.
    primary_recovery_task = asyncio.create_task(
        primary_recovery_monitor()
    )

    print(
        f"Primary: {PRIMARY_OLLAMA}"
    )

    print(
        f"Backup: {BACKUP_OLLAMA}"
    )

    print(
        f"Primary available: {primary_available}"
    )

    yield

    if primary_recovery_task:
        primary_recovery_task.cancel()

        try:
            await primary_recovery_task
        except asyncio.CancelledError:
            pass

    await client.aclose()


app = FastAPI(
    title="Ollama Failover Gateway",
    lifespan=lifespan,
)


# ============================================================
# Helpers
# ============================================================

def get_client() -> httpx.AsyncClient:
    if client is None:
        raise RuntimeError(
            "HTTP client not initialized"
        )

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


async def update_primary_state() -> bool:
    global primary_available

    available = await ollama_health(
        PRIMARY_OLLAMA,
        PRIMARY_HEALTH_TIMEOUT,
    )

    async with state_lock:
        previous = primary_available
        primary_available = available

    if available and not previous:
        print(
            "Primary Ollama is available. "
            "Using primary for new requests."
        )

    elif not available and previous:
        print(
            "Primary Ollama became unavailable. "
            "Failover is active."
        )

    return available


# ============================================================
# Wake-on-LAN
# ============================================================

def send_wol() -> None:
    mac = (
        PRIMARY_MAC
        .replace(":", "")
        .replace("-", "")
        .strip()
    )

    if len(mac) != 12:
        raise ValueError(
            f"Invalid MAC address: {PRIMARY_MAC}"
        )

    try:
        mac_bytes = bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError(
            f"Invalid MAC address: {PRIMARY_MAC}"
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

        print(
            f"Sent Wake-on-LAN to {PRIMARY_MAC}"
        )

    finally:
        sock.close()


async def wake_primary_if_needed() -> None:
    global last_wol_time

    now = time.monotonic()

    async with state_lock:
        cooldown_active = (
            now - last_wol_time
            < WOL_COOLDOWN
        )

    if cooldown_active:
        return

    async with state_lock:
        last_wol_time = now

    try:
        send_wol()

    except Exception as exc:
        print(
            f"Wake-on-LAN failed: {exc}"
        )


# ============================================================
# Background primary recovery
# ============================================================

async def primary_recovery_monitor() -> None:
    global primary_available

    while True:
        try:
            available = await ollama_health(
                PRIMARY_OLLAMA,
                PRIMARY_HEALTH_TIMEOUT,
            )

            async with state_lock:
                previous = primary_available
                primary_available = available

            if available and not previous:
                print(
                    "Primary Ollama recovered. "
                    "New requests will use primary."
                )

            elif not available and previous:
                print(
                    "Primary Ollama unavailable. "
                    "Backup is active."
                )

            await asyncio.sleep(
                PRIMARY_RECOVERY_INTERVAL
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"Primary recovery monitor error: {exc}"
            )

            await asyncio.sleep(
                PRIMARY_RECOVERY_INTERVAL
            )

# ============================================================
# Backend selection
# ============================================================

async def select_backend() -> str:
    """
    Primary is preferred.

    If primary is unavailable:
      1. Send WoL to primary.
      2. Immediately use backup.

    Do not wait for primary recovery.
    """

    global primary_available

    async with state_lock:
        available = primary_available

    if available:
        return PRIMARY_OLLAMA

    # Primary is unavailable.
    # Attempt WoL without waiting.
    asyncio.create_task(
        wake_primary_if_needed()
    )

    # Immediately fail over to backup.
    return BACKUP_OLLAMA


# ============================================================
# Headers
# ============================================================

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


# ============================================================
# Health endpoints
# ============================================================

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
        "active_backend": (
            "primary"
            if primary
            else "backup"
        ),
    }


@app.get("/backend")
async def backend_status():
    primary = await ollama_health(
        PRIMARY_OLLAMA,
        PRIMARY_HEALTH_TIMEOUT,
    )

    backup = await ollama_health(
        BACKUP_OLLAMA,
        BACKUP_HEALTH_TIMEOUT,
    )

    return {
        "primary": {
            "available": primary,
            "url": PRIMARY_OLLAMA,
        },
        "backup": {
            "available": backup,
            "url": BACKUP_OLLAMA,
        },
        "active_backend": (
            "primary"
            if primary
            else "backup"
        ),
    }


# ============================================================
# Generic Ollama proxy
# ============================================================

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
        upstream_request = (
            get_client().build_request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
        )

        upstream_response = (
            await get_client().send(
                upstream_request,
                stream=True,
            )
        )

    except httpx.HTTPError as exc:

        # Primary may have disappeared after the
        # background health check.
        #
        # Immediately retry through backup.

        if backend == PRIMARY_OLLAMA:

            print(
                "Primary request failed. "
                "Retrying through backup."
            )

            async with state_lock:
                global primary_available
                primary_available = False

            # Trigger WoL without waiting.
            asyncio.create_task(
                wake_primary_if_needed()
            )

            backup_url = (
                f"{BACKUP_OLLAMA}/{path}"
            )

            if request.url.query:
                backup_url += (
                    f"?{request.url.query}"
                )

            backup_request = (
                get_client().build_request(
                    method=request.method,
                    url=backup_url,
                    headers=headers,
                    content=body,
                )
            )

            try:
                upstream_response = (
                    await get_client().send(
                        backup_request,
                        stream=True,
                    )
                )

            except httpx.HTTPError as backup_exc:
                return JSONResponse(
                    status_code=502,
                    content={
                        "error": (
                            "Both Ollama backends "
                            "are unavailable."
                        ),
                        "detail": str(
                            backup_exc
                        ),
                    },
                )

        else:
            return JSONResponse(
                status_code=502,
                content={
                    "error": (
                        "Backup Ollama "
                        "is unavailable."
                    ),
                    "detail": str(exc),
                },
            )

    async def stream_response() -> AsyncIterator[bytes]:
        try:
            async for chunk in (
                upstream_response.aiter_raw()
            ):
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