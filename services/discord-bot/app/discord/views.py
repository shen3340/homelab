import logging
from typing import Any

import discord

from app.database.requests import create_movie_request
from app.media.radarr import RadarrError

logger = logging.getLogger(__name__)


class MovieSearchView(discord.ui.View):
    def __init__(
        self,
        bot: Any,
        movies: list[dict[str, Any]],
        requester_id: int,
    ):
        super().__init__(timeout=120)

        self.bot = bot
        self.movies = movies
        self.requester_id = requester_id

        for index, movie in enumerate(movies):
            self.add_item(
                MovieSelectButton(
                    bot=bot,
                    movie=movie,
                    requester_id=requester_id,
                    index=index,
                )
            )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This movie search belongs to someone else.",
                ephemeral=True,
            )

            return False

        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


class MovieSelectButton(discord.ui.Button):
    def __init__(
        self,
        bot: Any,
        movie: dict[str, Any],
        requester_id: int,
        index: int,
    ):
        title = movie.get(
            "title",
            "Unknown",
        )

        super().__init__(
            label=f"{index + 1}. {title[:70]}",
            style=discord.ButtonStyle.primary,
            custom_id=f"movie-select-{requester_id}-{index}",
        )

        self.bot = bot
        self.movie = movie
        self.requester_id = requester_id

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer()

        tmdb_id = self.movie.get("tmdbId")

        if not tmdb_id:
            await interaction.followup.send(
                "❌ Selected movie does not have a TMDB ID."
            )

            return

        try:
            movie = await self.bot.radarr.get_movie(
                tmdb_id=tmdb_id,
            )

        except RadarrError:
            logger.exception(
                "Failed to retrieve movie details for TMDB ID %s",
                tmdb_id,
            )

            await interaction.followup.send(
                "❌ Unable to retrieve movie details from Radarr."
            )

            return

        view = MovieRequestView(
            bot=self.bot,
            movie=movie,
            requester_id=self.requester_id,
        )

        embed = build_movie_embed(
            movie,
            title="Movie Selected",
        )

        await interaction.followup.send(
            embed=embed,
            view=view,
        )


class MovieRequestView(discord.ui.View):
    def __init__(
        self,
        bot: Any,
        movie: dict[str, Any],
        requester_id: int,
    ):
        super().__init__(timeout=120)

        self.bot = bot
        self.movie = movie
        self.requester_id = requester_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This movie request belongs to someone else.",
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Request",
        style=discord.ButtonStyle.success,
    )
    async def request_movie(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer()

        title = self.movie.get(
            "title",
            "Unknown",
        )

        year = self.movie.get(
            "year",
            "Unknown",
        )

        try:
            added_movie = await self.bot.radarr.add_movie(
                movie=self.movie,
            )

        except RadarrError:
            logger.exception(
                "Failed to add movie %s (%s)",
                title,
                year,
            )

            await interaction.followup.send("❌ Unable to add movie to Radarr.")

            return

        for child in self.children:
            child.disabled = True

        # Parent-channel message.
        parent_embed = build_request_embed(
            title=title,
            year=year,
            requester=interaction.user,
            status="searching",
        )

        parent_message = await interaction.followup.send(
            embed=parent_embed,
            wait=True,
        )

        if interaction.channel is None:
            logger.error("Unable to determine Discord channel for request")

            return

        # Thread owns status/history.
        thread = await interaction.channel.create_thread(
            name=f"🎬 {title} ({year})",
            type=discord.ChannelType.public_thread,
            auto_archive_duration=10080,
        )

        request_id = create_movie_request(
            radarr_movie_id=added_movie["id"],
            tmdb_id=added_movie.get("tmdbId"),
            title=title,
            year=year,
            discord_guild_id=interaction.guild_id,
            discord_channel_id=interaction.channel_id,
            discord_message_id=parent_message.id,
            discord_thread_id=thread.id,
            requester_id=interaction.user.id,
            status="searching",
        )

        thread_embed = build_status_embed(
            title=title,
            year=year,
            status="searching",
        )

        await thread.send(
            embed=thread_embed,
        )

        logger.info(
            "Created movie request %s for %s (%s) with Discord thread %s",
            request_id,
            title,
            year,
            thread.id,
        )

        self.stop()


def build_request_embed(
    *,
    title: str,
    year: Any,
    requester: discord.abc.User,
    status: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎬 {title}",
        description=f"**{year}**",
    )

    embed.add_field(
        name="Requested by",
        value=requester.mention,
        inline=True,
    )

    embed.add_field(
        name="Status",
        value=status_text(status),
        inline=True,
    )

    return embed


def build_status_embed(
    *,
    title: str,
    year: Any,
    status: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎬 {title}",
        description=f"**{year}**",
    )

    embed.add_field(
        name="Status",
        value=status_text(status),
        inline=False,
    )

    return embed


def status_text(
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


def build_movie_embed(
    movie: dict[str, Any],
    title: str,
) -> discord.Embed:
    movie_title = movie.get(
        "title",
        "Unknown",
    )

    year = movie.get(
        "year",
        "Unknown",
    )

    overview = movie.get(
        "overview",
        "",
    )

    if len(overview) > 500:
        overview = f"{overview[:497]}..."

    embed = discord.Embed(
        title=title,
        description=f"**{movie_title}** ({year})",
    )

    if overview:
        embed.add_field(
            name="Overview",
            value=overview,
            inline=False,
        )

    tmdb_id = movie.get("tmdbId")

    if tmdb_id:
        embed.add_field(
            name="TMDB",
            value=str(tmdb_id),
            inline=True,
        )

    runtime = movie.get("runtime")

    if runtime:
        embed.add_field(
            name="Runtime",
            value=f"{runtime} minutes",
            inline=True,
        )

    return embed
