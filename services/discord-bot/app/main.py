import asyncio
import logging

import uvicorn

from app.config import settings
from app.database.database import initialize_database
from app.discord.bot import MediaBot
from app.discord.commands import register_commands
from app.logging import configure_logging
from app.webhooks.radarr import create_webhook_app

logger = logging.getLogger(__name__)


async def run_discord(
    bot: MediaBot,
) -> None:
    await bot.start(
        settings.discord_token,
    )


async def run_webhook_server(
    bot: MediaBot,
) -> None:
    app = create_webhook_app(
        bot,
    )

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )

    server = uvicorn.Server(
        config,
    )

    await server.serve()


async def run() -> None:
    initialize_database()

    bot = MediaBot()

    register_commands(bot)

    try:
        await asyncio.gather(
            run_discord(bot),
            run_webhook_server(bot),
        )

    finally:
        await bot.close()


def main() -> None:
    configure_logging()

    logger.info("Starting Discord bot")

    asyncio.run(run())


if __name__ == "__main__":
    main()
