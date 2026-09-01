import logging

import discord
from discord import app_commands

from app.discord.bot import MediaBot
from app.discord.views import MovieSearchView
from app.media.radarr import RadarrError


logger = logging.getLogger(__name__)


def register_commands(bot: MediaBot) -> None:
    @bot.tree.command(
        name="search",
        description="Search Radarr for a movie",
        guild=bot.guild,
    )
    @app_commands.describe(
        query="Movie title to search for",
    )
    async def search(
        interaction: discord.Interaction,
        query: str,
    ) -> None:
        await interaction.response.defer()

        logger.info(
            "Movie search requested by %s: %s",
            interaction.user,
            query,
        )

        try:
            results = await bot.radarr.search(query)

        except RadarrError:
            logger.exception(
                "Radarr search failed for %r",
                query,
            )

            await interaction.followup.send(
                "❌ Unable to communicate with Radarr."
            )

            return

        if not results:
            await interaction.followup.send(
                f"❌ No movies found for `{query}`."
            )

            return

        results = results[:5]

        embed = discord.Embed(
            title=f"Movie Search: {query}",
            description=(
                "Select a movie below to view details "
                "and request it."
            ),
        )

        for index, movie in enumerate(
            results,
            start=1,
        ):
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

            if len(overview) > 200:
                overview = f"{overview[:197]}..."

            value = f"**Year:** {year}"

            if overview:
                value += f"\n{overview}"

            embed.add_field(
                name=f"{index}. {movie_title}",
                value=value,
                inline=False,
            )

        view = MovieSearchView(
            bot=bot,
            movies=results,
            requester_id=interaction.user.id,
        )

        await interaction.followup.send(
            embed=embed,
            view=view,
        )