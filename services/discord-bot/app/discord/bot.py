import logging
from typing import Any

import discord
from discord.ext import commands

from app.config import settings
from app.database.requests import (
    get_movie_request_by_radarr_id,
    update_movie_request_status,
)
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

    async def handle_radarr_event(
        self,
        payload: dict[str, Any],
    ) -> None:
        event_type = payload.get(
            "eventType",
        )

        movie = payload.get(
            "movie",
        )

        if not isinstance(movie, dict):
            logger.warning(
                "Radarr event %s did not contain movie data",
                event_type,
            )

            return

        radarr_movie_id = movie.get(
            "id",
        )

        if not radarr_movie_id:
            logger.warning(
                "Radarr event %s did not contain movie ID",
                event_type,
            )

            return

        logger.info(
            "Processing Radarr event %s for movie %s",
            event_type,
            radarr_movie_id,
        )

        request = get_movie_request_by_radarr_id(
            radarr_movie_id,
        )

        if request is None:
            logger.info(
                "Ignoring Radarr event %s for untracked movie %s",
                event_type,
                radarr_movie_id,
            )

            return

        status = self._map_radarr_event_to_status(
            event_type,
        )

        if status is None:
            logger.info(
                "No status mapping for Radarr event %s",
                event_type,
            )

            return

        update_movie_request_status(
            request["id"],
            status,
        )

        await self._update_discord_request(
            request=request,
            status=status,
            event_type=event_type,
        )

    @staticmethod
    def _map_radarr_event_to_status(
        event_type: str | None,
    ) -> str | None:
        mapping = {
            "Grab": "downloading",
            "Download": "downloading",
            "DownloadFailed": "failed",
            "MovieFileImport": "ready",
            "MovieFileUpgrade": "ready",
            "Import": "ready",
            "Upgrade": "ready",
            "MovieFileDelete": "removed",
        }

        return mapping.get(event_type)

    async def _update_discord_request(
        self,
        *,
        request: dict[str, Any],
        status: str,
        event_type: str | None,
    ) -> None:
        try:
            channel = self.get_channel(
                request["discord_channel_id"],
            )

            if channel is None:
                channel = await self.fetch_channel(
                    request["discord_channel_id"],
                )

            if not isinstance(
                channel,
                discord.abc.Messageable,
            ):
                logger.error(
                    "Discord channel %s is not messageable",
                    request["discord_channel_id"],
                )

                return

            # ----------------------------------------
            # Parent message
            # ----------------------------------------

            parent_message = await channel.fetch_message(
                request["discord_message_id"],
            )

            parent_embed = discord.Embed(
                title=f"🎬 {request['title']}",
                description=(
                    f"**{request['year']}**"
                    if request["year"]
                    else None
                ),
            )

            parent_embed.add_field(
                name="Requested by",
                value=f"<@{request['requester_id']}>",
                inline=True,
            )

            parent_embed.add_field(
                name="Status",
                value=self._status_text(status),
                inline=True,
            )

            await parent_message.edit(
                embed=parent_embed,
            )

            # ----------------------------------------
            # Thread
            # ----------------------------------------

            thread_id = request.get(
                "discord_thread_id",
            )

            if not thread_id:
                logger.warning(
                    "Request %s has no Discord thread",
                    request["id"],
                )

                return

            thread = self.get_channel(
                thread_id,
            )

            if thread is None:
                thread = await self.fetch_channel(
                    thread_id,
                )

            if not isinstance(
                thread,
                discord.Thread,
            ):
                logger.error(
                    "Discord channel %s is not a thread",
                    thread_id,
                )

                return

            # Add status event to history.
            status_embed = discord.Embed(
                title=f"🎬 {request['title']}",
                description=(
                    f"**{request['year']}**"
                    if request["year"]
                    else None
                ),
            )

            status_embed.add_field(
                name="Status",
                value=self._status_text(status),
                inline=False,
            )

            status_embed.set_footer(
                text=f"Radarr event: {event_type}",
            )

            await thread.send(
                embed=status_embed,
            )

            logger.info(
                "Updated Discord request %s: %s",
                request["id"],
                status,
            )

        except discord.NotFound:
            logger.error(
                "Discord message/thread no longer exists for request %s",
                request["id"],
            )

        except discord.Forbidden:
            logger.error(
                "Discord bot does not have permission to update "
                "request %s",
                request["id"],
            )

        except discord.HTTPException:
            logger.exception(
                "Failed to update Discord request %s",
                request["id"],
            )
    @staticmethod
    def _status_text(
        status: str,
    ) -> str:
        statuses = {
            "searching": "🔎 Searching for release",
            "downloading": "⬇️ Downloading",
            "ready": "🍿 Ready to watch",
            "failed": "❌ Download failed",
            "removed": "🗑️ Movie file removed",
        }

        return statuses.get(
            status,
            "❓ Unknown",
        )
