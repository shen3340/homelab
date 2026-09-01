import logging

import discord
from discord.ext import commands

from app.config import settings
from app.media.radarr import RadarrClient

logger = logging.getLogger(__name__)


class MediaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

        self.guild = discord.Object(
            id=settings.discord_guild_id,
        )

        self.radarr = RadarrClient(
            base_url=settings.radarr_url,
            api_key=settings.radarr_api_key,
        )

    async def setup_hook(self) -> None:
        logger.info(
            "Syncing Discord commands to guild %s",
            settings.discord_guild_id,
        )

        await self.tree.sync(
            guild=self.guild,
        )

        logger.info("Discord commands synced")

    async def close(self) -> None:
        logger.info("Closing bot")

        await self.radarr.close()

        await super().close()

    async def on_ready(self) -> None:
        logger.info(
            "Logged in as %s (%s)",
            self.user,
            self.user.id if self.user else "unknown",
        )

        radarr_available = await self.radarr.health()

        logger.info(
            "Radarr available: %s",
            radarr_available,
        )
