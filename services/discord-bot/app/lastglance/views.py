import asyncio
import logging
from typing import Callable

import discord


logger = logging.getLogger(
    "discord-bot.lastglance.views",
)


LASTGLANCE_URL = "https://lastglance.shen3340.com"


class ChoreView(
    discord.ui.View,
):
    def __init__(
        self,
        chore_id: str,
        chore_name: str,
        complete_chore: Callable[
            [str],
            dict,
        ],
    ) -> None:
        super().__init__(
            timeout=None,
        )

        self.chore_id = chore_id
        self.chore_name = chore_name
        self.complete_chore = complete_chore

        complete_button = discord.ui.Button(
            label="Complete",
            emoji="✅",
            style=(discord.ButtonStyle.success),
            custom_id=(f"lastglance:complete:{chore_id}"),
        )

        complete_button.callback = self.complete_callback

        self.add_item(
            complete_button,
        )

        self.add_item(
            discord.ui.Button(
                label="Open LastGLANCE",
                emoji="🔗",
                style=(discord.ButtonStyle.link),
                url=LASTGLANCE_URL,
            )
        )

    async def complete_callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer()

        try:
            await asyncio.to_thread(
                self.complete_chore,
                self.chore_id,
            )

        except ValueError as exc:
            await interaction.followup.send(
                f"❌ Unable to complete chore: {exc}",
                ephemeral=True,
            )
            return

        except Exception:
            logger.exception(
                "Failed completing LastGLANCE chore %s",
                self.chore_id,
            )

            await interaction.followup.send(
                "❌ Unable to complete chore. Check the bot logs.",
                ephemeral=True,
            )
            return

        await interaction.edit_original_response(
            content=(
                f"✅ **Completed**\n\n**{self.chore_name}**\n\nCompleted just now."
            ),
            view=CompletedView(),
        )


class CompletedView(
    discord.ui.View,
):
    def __init__(self) -> None:
        super().__init__(
            timeout=None,
        )

        self.add_item(
            discord.ui.Button(
                label="Open LastGLANCE",
                emoji="🔗",
                style=(discord.ButtonStyle.link),
                url=LASTGLANCE_URL,
            )
        )
