import logging

from app.config import settings
from app.discord.bot import MediaBot
from app.discord.commands import register_commands
from app.logging import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()

    logger.info("Starting Discord bot")

    bot = MediaBot()

    register_commands(bot)

    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
