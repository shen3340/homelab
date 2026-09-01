import logging
from typing import Any

from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)


def create_webhook_app(
    bot: Any,
) -> FastAPI:
    app = FastAPI(
        title="Discord Bot Webhooks",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "healthy",
        }

    @app.post("/webhooks/radarr")
    async def radarr_webhook(
        request: Request,
    ) -> dict[str, str]:
        try:
            payload = await request.json()

        except Exception:
            logger.exception("Failed to parse Radarr webhook payload")

            return {
                "status": "invalid",
            }

        event_type = payload.get(
            "eventType",
            "Unknown",
        )

        logger.info(
            "Received Radarr webhook: %s",
            event_type,
        )

        await bot.handle_radarr_event(
            payload,
        )

        return {
            "status": "accepted",
        }

    return app
