import os
import time
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel
from rag import delete_page, index_page

load_dotenv()

# region Configuration

WEBHOOK_HOST = os.getenv(
    "WEBHOOK_HOST",
    "0.0.0.0",
)

WEBHOOK_PORT = int(
    os.getenv(
        "WEBHOOK_PORT",
        "8000",
    )
)

BOOKSTACK_WEBHOOK_IP = os.getenv(
    "BOOKSTACK_WEBHOOK_IP",
)

# endregion

# region FastAPI

app = FastAPI(
    title="BookStack RAG Webhook",
    version="1.0.0",
)

# endregion


# region Validating Source IP
def validate_source_ip(
    request: Request,
) -> None:

    client_ip = request.client.host if request.client else None

    if request.client is None:
        print(
            "bookstack_webhook forbidden reason=no_client",
            flush=True,
        )

        raise HTTPException(
            status_code=403,
            detail="Unable to determine request source",
        )

    if BOOKSTACK_WEBHOOK_IP and client_ip != BOOKSTACK_WEBHOOK_IP:
        print(
            f"bookstack_webhook forbidden "
            f"source_ip={client_ip} "
            f"allowed_ip={BOOKSTACK_WEBHOOK_IP}",
            flush=True,
        )

        raise HTTPException(
            status_code=403,
            detail="Invalid request source",
        )


# endregion


# region Request model
class BookStackWebhook(BaseModel):
    event: str
    related_item: dict[str, Any] | None = None


# endregion


# region Background processing
def process_event(
    event: str,
    page_id: int,
) -> None:

    started = time.monotonic()

    print(
        f"bookstack_webhook event={event} page_id={page_id}",
        flush=True,
    )

    try:
        if event in {
            "page_create",
            "page_update",
        }:
            print(
                f"bookstack_webhook indexing page_id={page_id}",
                flush=True,
            )

            index_page(page_id)

        elif event == "page_delete":
            print(
                f"bookstack_webhook deleting page_id={page_id}",
                flush=True,
            )

            delete_page(page_id)

        else:
            print(
                f"bookstack_webhook ignored event={event} page_id={page_id}",
                flush=True,
            )

            return

        duration_ms = int((time.monotonic() - started) * 1000)

        print(
            f"bookstack_webhook "
            f"completed "
            f"event={event} "
            f"page_id={page_id} "
            f"duration_ms={duration_ms}",
            flush=True,
        )

    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)

        print(
            f"bookstack_webhook "
            f"failed "
            f"event={event} "
            f"page_id={page_id} "
            f"duration_ms={duration_ms} "
            f'error="{exc}"',
            flush=True,
        )


# endregion

# region Routes


@app.get("/health")
def health():
    return {
        "status": "healthy",
    }


@app.post("/webhooks/bookstack")
def bookstack_webhook(
    request: Request,
    payload: BookStackWebhook,
    background_tasks: BackgroundTasks,
):
    validate_source_ip(request)

    event = payload.event

    if event not in {
        "page_create",
        "page_update",
        "page_delete",
    }:
        return {
            "status": "ignored",
            "event": event,
        }

    if not payload.related_item:
        raise HTTPException(
            status_code=400,
            detail="Webhook missing related_item",
        )

    page_id = payload.related_item.get("id")

    if page_id is None:
        raise HTTPException(
            status_code=400,
            detail="Webhook missing page ID",
        )

    background_tasks.add_task(
        process_event,
        event,
        int(page_id),
    )

    return {
        "status": "accepted",
        "event": event,
        "page_id": int(page_id),
    }


# endregion

# region Main
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=WEBHOOK_HOST,
        port=WEBHOOK_PORT,
    )
# endregion
