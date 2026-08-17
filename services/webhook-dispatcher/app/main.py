# region Libraries

import hashlib
import hmac
import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

# endregion

# region Config

GITHUB_WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "shen3340/homelab")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "refs/heads/main")

PORTAINER_WEBHOOKS: dict[str, str] = {
    key.removeprefix("PORTAINER_WEBHOOK_").lower(): value
    for key, value in os.environ.items()
    if key.startswith("PORTAINER_WEBHOOK_") and value
}

PORTAINER_URL = os.getenv(
    "PORTAINER_URL",
    "http://portainer:9000",
)

PORTAINER_TIMEOUT = float(os.getenv("PORTAINER_TIMEOUT", "10"))

# endregion

# region Logging

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("webhook-dispatcher")

# endregion

# region FastAPI

app = FastAPI(
    title="Homelab GitOps Webhook Dispatcher",
    docs_url="/docs",
    redoc_url="/redoc",
)

# endregion

# region Helpers


def verify_signature(payload: bytes, signature: str | None) -> bool:
    """Validate GitHub X-Hub-Signature-256."""

    if not signature:
        return False

    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    provided = signature.removeprefix("sha256=")

    return hmac.compare_digest(expected, provided)


def extract_changed_paths(payload: dict[str, Any]) -> set[str]:
    """Collect added, modified, and removed paths across all commits."""

    paths: set[str] = set()

    for commit in payload.get("commits", []):
        for key in ("added", "modified", "removed"):
            for path in commit.get(key, []):
                if isinstance(path, str):
                    paths.add(path)

    return paths


def get_affected_stacks(paths: set[str]) -> set[str]:
    """
    Convert repository paths into stack names.

    Example:
        stacks/jellyfin/compose.yml
        -> jellyfin
    """

    stacks: set[str] = set()

    for path in paths:
        parts = path.split("/")

        if len(parts) < 2:
            continue

        if parts[0] != "stacks":
            continue

        stack_name = parts[1].strip()

        if stack_name:
            stacks.add(stack_name)

    return stacks


async def trigger_portainer_stack(
    stack_name: str,
    webhook_key: str,
) -> bool:
    """Trigger one Portainer GitOps webhook."""

    webhook_url = (
        f"{PORTAINER_URL}/api/stacks/webhooks/{webhook_key}"
    )

    logger.info(
        "Triggering Portainer stack=%s",
        stack_name,
    )

    try:
        async with httpx.AsyncClient(
            timeout=PORTAINER_TIMEOUT,
            follow_redirects=False,
        ) as client:
            response = await client.post(webhook_url)

        if 200 <= response.status_code < 300:
            logger.info(
                "Portainer trigger succeeded stack=%s status=%s",
                stack_name,
                response.status_code,
            )
            return True

        logger.error(
            "Portainer trigger failed stack=%s status=%s",
            stack_name,
            response.status_code,
        )

        return False

    except httpx.RequestError as exc:
        logger.error(
            "Portainer trigger request failed stack=%s error=%s",
            stack_name,
            type(exc).__name__,
        )
        return False
# endregion

# region Routes


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, Any]:

    # -------------------------------------------------------------------------
    # Read raw request body before parsing JSON.
    # Signature must be calculated against exact raw bytes.
    # -------------------------------------------------------------------------

    body = await request.body()

    delivery_id = x_github_delivery or "unknown"

    logger.info(
        "Received GitHub webhook delivery=%s event=%s",
        delivery_id,
        x_github_event,
    )

    # -------------------------------------------------------------------------
    # Signature validation
    # -------------------------------------------------------------------------

    if not verify_signature(body, x_hub_signature_256):
        logger.warning(
            "Invalid GitHub signature delivery=%s",
            delivery_id,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid signature",
        )

    # -------------------------------------------------------------------------
    # Event validation
    # -------------------------------------------------------------------------

    if x_github_event != "push":
        logger.info(
            "Ignoring GitHub event delivery=%s event=%s",
            delivery_id,
            x_github_event,
        )

        return {
            "status": "ignored",
            "reason": "unsupported_event",
        }

    # -------------------------------------------------------------------------
    # Parse payload
    # -------------------------------------------------------------------------

    try:
        payload: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError:
        logger.warning(
            "Invalid JSON delivery=%s",
            delivery_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON",
        )

    # -------------------------------------------------------------------------
    # Repository validation
    # -------------------------------------------------------------------------

    repository = payload.get("repository", {}).get("full_name")

    if repository != GITHUB_REPOSITORY:
        logger.warning(
            "Ignoring unexpected repository delivery=%s repository=%s",
            delivery_id,
            repository,
        )

        return {
            "status": "ignored",
            "reason": "unexpected_repository",
        }

    # -------------------------------------------------------------------------
    # Branch validation
    # -------------------------------------------------------------------------

    ref = payload.get("ref")

    if ref != GITHUB_BRANCH:
        logger.info(
            "Ignoring non-target branch delivery=%s ref=%s",
            delivery_id,
            ref,
        )

        return {
            "status": "ignored",
            "reason": "unexpected_branch",
        }

    # -------------------------------------------------------------------------
    # Commit information
    # -------------------------------------------------------------------------

    commit_sha = payload.get("after", "unknown")

    # -------------------------------------------------------------------------
    # Changed paths
    # -------------------------------------------------------------------------

    changed_paths = extract_changed_paths(payload)

    logger.info(
        "GitHub push delivery=%s repository=%s ref=%s commit=%s paths=%s",
        delivery_id,
        repository,
        ref,
        commit_sha,
        sorted(changed_paths),
    )

    # -------------------------------------------------------------------------
    # Determine affected stacks
    # -------------------------------------------------------------------------

    affected_stacks = get_affected_stacks(changed_paths)

    if not affected_stacks:
        logger.info(
            "No stack changes delivery=%s",
            delivery_id,
        )

        return {
            "status": "ok",
            "delivery_id": delivery_id,
            "commit": commit_sha,
            "changed_paths": sorted(changed_paths),
            "affected_stacks": [],
            "triggered": [],
            "failed": [],
        }

    logger.info(
        "Affected stacks delivery=%s stacks=%s",
        delivery_id,
        sorted(affected_stacks),
    )

    # -------------------------------------------------------------------------
    # Trigger Portainer stacks
    # -------------------------------------------------------------------------

    triggered: list[str] = []
    failed: list[str] = []
    unregistered: list[str] = []

    for stack_name in sorted(affected_stacks):
        webhook_key = PORTAINER_WEBHOOKS.get(stack_name)

        if not webhook_key:
            logger.warning(
                "No Portainer webhook registered stack=%s",
                stack_name,
            )

            unregistered.append(stack_name)
            continue

        success = await trigger_portainer_stack(
            stack_name=stack_name,
            webhook_key=webhook_key,
        )

        if success:
            triggered.append(stack_name)
        else:
            failed.append(stack_name)

    # -------------------------------------------------------------------------
    # Final result
    # -------------------------------------------------------------------------

    logger.info(
        "Webhook processing complete delivery=%s commit=%s "
        "triggered=%s failed=%s unregistered=%s",
        delivery_id,
        commit_sha,
        triggered,
        failed,
        unregistered,
    )

    return {
        "status": "ok",
        "delivery_id": delivery_id,
        "commit": commit_sha,
        "changed_paths": sorted(changed_paths),
        "affected_stacks": sorted(affected_stacks),
        "triggered": triggered,
        "failed": failed,
        "unregistered": unregistered,
    }


# endregion
