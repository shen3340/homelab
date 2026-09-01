import logging
from typing import Any

import discord

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

        year = movie.get(
            "year",
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

            await interaction.followup.send(
                "❌ Unable to add movie to Radarr."
            )

            return

        button.disabled = True

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="✅ Movie Requested",
            description=f"**{title}** ({year})",
        )

        movie_path = added_movie.get(
            "path",
        )

        if movie_path:
            embed.add_field(
                name="Path",
                value=movie_path,
                inline=False,
            )

        embed.add_field(
            name="Status",
            value="🔎 Radarr is searching for a release.",
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.danger,
    )
    async def cancel_movie(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❌ Movie request cancelled.",
            embed=None,
            view=self,
        )

        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


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