#region Libraries

import asyncio
import hashlib
import hmac
import json
import logging
import os
from collections import deque
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

#endregion


#region Config

GITHUB_WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "shen3340/homelab")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "refs/heads/main")

PORTAINER_URL = os.environ["PORTAINER_URL"].rstrip("/")
PORTAINER_API_KEY = os.environ["PORTAINER_API_KEY"]

PORTAINER_TIMEOUT = float(os.getenv("PORTAINER_TIMEOUT", "10"))
MAX_PROCESSED_DELIVERIES = int(os.getenv("MAX_PROCESSED_DELIVERIES", "1000"))

processed_deliveries: set[str] = set()
processed_delivery_order: deque[str] = deque()

#endregion


#region Logging

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("webhook-dispatcher")

#endregion


#region FastAPI

app = FastAPI(
    title="Homelab GitOps Webhook Dispatcher",
    docs_url="/docs",
    redoc_url="/redoc",
)

#endregion


#region Helpers


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
    Convert repository paths into Portainer stack names.

    Supported layouts:
        stacks/<stack-name>/...
        services/<service-name>/...

    Examples:
        stacks/jellyfin/compose.yml
        -> jellyfin

        services/ollama-gateway/compose.yml
        -> ollama-gateway
    """

    stacks: set[str] = set()

    managed_roots = {"stacks", "services"}

    for path in paths:
        parts = path.split("/")

        if len(parts) < 2:
            continue

        if parts[0] not in managed_roots:
            continue

        stack_name = parts[1].strip()

        if stack_name:
            stacks.add(stack_name)

    return stacks


def is_duplicate_delivery(delivery_id: str) -> bool:
    """Return True if delivery was already processed."""

    if delivery_id in processed_deliveries:
        return True

    processed_deliveries.add(delivery_id)
    processed_delivery_order.append(delivery_id)

    while len(processed_delivery_order) > MAX_PROCESSED_DELIVERIES:
        oldest = processed_delivery_order.popleft()
        processed_deliveries.discard(oldest)

    return False


async def get_portainer_stacks(
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Retrieve stacks from Portainer."""

    response = await client.get(
        f"{PORTAINER_URL}/api/stacks",
    )

    if response.status_code != 200:
        logger.error(
            "Portainer stack discovery failed status=%s response=%s",
            response.status_code,
            response.text[:500],
        )

        response.raise_for_status()

    stacks = response.json()

    if not isinstance(stacks, list):
        raise RuntimeError("Portainer /api/stacks returned unexpected data")

    logger.info(
        "Discovered Portainer stacks count=%s",
        len(stacks),
    )

    return stacks


async def find_portainer_stack(
    client: httpx.AsyncClient,
    stack_name: str,
) -> dict[str, Any] | None:
    """Find a Portainer stack by name."""

    stacks = await get_portainer_stacks(client)

    for stack in stacks:
        name = stack.get("Name")

        if name == stack_name:
            return stack

    return None


async def redeploy_portainer_stack(
    client: httpx.AsyncClient,
    stack: dict[str, Any],
    max_attempts: int = 3,
) -> bool:
    """Pull latest Git state and redeploy a Portainer Git stack."""

    stack_id = stack.get("Id")
    stack_name = stack.get("Name")
    endpoint_id = stack.get("EndpointId")

    if not stack_id:
        logger.error(
            "Portainer stack missing ID stack=%s",
            stack_name,
        )
        return False

    if not endpoint_id:
        logger.error(
            "Portainer stack missing endpoint ID stack=%s id=%s",
            stack_name,
            stack_id,
        )
        return False

    git_config = stack.get("GitConfig")

    if not git_config:
        logger.warning(
            "Stack is not Git-backed stack=%s id=%s",
            stack_name,
            stack_id,
        )
        return False

    url = (
        f"{PORTAINER_URL}/api/stacks/"
        f"{stack_id}/git/redeploy"
        f"?endpointId={endpoint_id}"
    )

    payload = {
        "repullImageAndRedeploy": True,
        "prune": False,
    }

    delays = [0, 1, 3]

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Redeploying Portainer stack=%s id=%s "
            "endpoint=%s attempt=%s/%s",
            stack_name,
            stack_id,
            endpoint_id,
            attempt,
            max_attempts,
        )

        try:
            response = await client.put(
                url,
                json=payload,
            )

            if 200 <= response.status_code < 300:
                logger.info(
                    "Portainer redeploy succeeded "
                    "stack=%s id=%s status=%s",
                    stack_name,
                    stack_id,
                    response.status_code,
                )
                return True

            logger.warning(
                "Portainer redeploy failed "
                "stack=%s id=%s attempt=%s/%s "
                "status=%s response=%s",
                stack_name,
                stack_id,
                attempt,
                max_attempts,
                response.status_code,
                response.text[:500],
            )

        except httpx.RequestError as exc:
            logger.warning(
                "Portainer redeploy request failed "
                "stack=%s id=%s attempt=%s/%s "
                "error=%s detail=%s",
                stack_name,
                stack_id,
                attempt,
                max_attempts,
                type(exc).__name__,
                str(exc),
            )

        if attempt < max_attempts:
            delay = delays[attempt]

            logger.info(
                "Retrying Portainer stack=%s in %s seconds",
                stack_name,
                delay,
            )

            await asyncio.sleep(delay)

    logger.error(
        "Portainer redeploy permanently failed "
        "stack=%s id=%s attempts=%s",
        stack_name,
        stack_id,
        max_attempts,
    )

    return False


#endregion


#region Routes


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, Any]:

    body = await request.body()

    if not x_github_delivery:
        logger.warning("Missing GitHub delivery ID")
        raise HTTPException(
            status_code=400,
            detail="Missing delivery ID",
        )

    delivery_id = x_github_delivery

    logger.info(
        "Received GitHub webhook delivery=%s event=%s",
        delivery_id,
        x_github_event,
    )

    if not verify_signature(body, x_hub_signature_256):
        logger.warning(
            "Invalid GitHub signature delivery=%s",
            delivery_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid signature",
        )

    if is_duplicate_delivery(delivery_id):
        logger.info(
            "Ignoring duplicate GitHub delivery=%s",
            delivery_id,
        )

        return {
            "status": "ignored",
            "reason": "duplicate_delivery",
            "delivery_id": delivery_id,
        }

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

    repository = payload.get("repository", {}).get("full_name")

    if repository != GITHUB_REPOSITORY:
        logger.warning(
            "Ignoring unexpected repository "
            "delivery=%s repository=%s",
            delivery_id,
            repository,
        )

        return {
            "status": "ignored",
            "reason": "unexpected_repository",
        }

    ref = payload.get("ref")

    if ref != GITHUB_BRANCH:
        logger.info(
            "Ignoring non-target branch "
            "delivery=%s ref=%s",
            delivery_id,
            ref,
        )

        return {
            "status": "ignored",
            "reason": "unexpected_branch",
        }

    commit_sha = payload.get("after", "unknown")

    changed_paths = extract_changed_paths(payload)

    logger.info(
        "GitHub push delivery=%s repository=%s "
        "ref=%s commit=%s paths=%s",
        delivery_id,
        repository,
        ref,
        commit_sha,
        sorted(changed_paths),
    )

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
            "unregistered": [],
        }

    logger.info(
        "Affected stacks delivery=%s stacks=%s",
        delivery_id,
        sorted(affected_stacks),
    )

    triggered: list[str] = []
    failed: list[str] = []
    unregistered: list[str] = []

    headers = {
        "X-API-Key": PORTAINER_API_KEY,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=PORTAINER_TIMEOUT,
        follow_redirects=False,
        verify=False,
        headers=headers,
    ) as client:

        for stack_name in sorted(affected_stacks):
            try:
                stack = await find_portainer_stack(
                    client=client,
                    stack_name=stack_name,
                )

                if not stack:
                    logger.warning(
                        "No Portainer stack found stack=%s",
                        stack_name,
                    )

                    unregistered.append(stack_name)
                    continue

                git_config = stack.get("GitConfig")

                if not git_config:
                    logger.warning(
                        "Portainer stack is not Git-backed "
                        "stack=%s id=%s",
                        stack_name,
                        stack.get("Id"),
                    )

                    failed.append(stack_name)
                    continue

                success = await redeploy_portainer_stack(
                    client=client,
                    stack=stack,
                )

                if success:
                    triggered.append(stack_name)
                else:
                    failed.append(stack_name)

            except httpx.HTTPError as exc:
                logger.exception(
                    "Portainer API error stack=%s error=%s",
                    stack_name,
                    exc,
                )
                failed.append(stack_name)

            except Exception as exc:
                logger.exception(
                    "Unexpected stack processing error "
                    "stack=%s error=%s",
                    stack_name,
                    exc,
                )
                failed.append(stack_name)

    logger.info(
        "Webhook processing complete "
        "delivery=%s commit=%s triggered=%s "
        "failed=%s unregistered=%s",
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


#endregion