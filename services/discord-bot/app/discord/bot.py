import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

from app.config import settings
from app.database.requests import (
    get_movie_request_by_radarr_id,
    update_movie_request_status,
)
from app.lastglance.service import (
    calculate_due_date,
    complete_chore,
    get_chore_sync_id,
    load_sync,
    parse_datetime,
)
from app.lastglance.views import ChoreView
from app.media.radarr import RadarrClient


logger = logging.getLogger(__name__)


class MediaBot(commands.Bot):
    def __init__(self) -> None:
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

        self.lastglance_task: asyncio.Task[None] | None = None

        self.lastglance_views_registered = False

    # ============================================================
    # Discord startup / shutdown
    # ============================================================

    async def setup_hook(self) -> None:
        logger.info(
            "Syncing Discord commands to guild %s",
            settings.discord_guild_id,
        )

        await self.tree.sync(
            guild=self.guild,
        )

        logger.info(
            "Discord commands synced",
        )

        await self._register_lastglance_views()

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

        if self.lastglance_task is None or self.lastglance_task.done():
            self.lastglance_task = asyncio.create_task(
                self._lastglance_loop(),
            )

            logger.info(
                "Started LastGLANCE notification loop",
            )

    async def close(self) -> None:
        logger.info(
            "Closing bot",
        )

        if self.lastglance_task is not None:
            self.lastglance_task.cancel()

            try:
                await self.lastglance_task
            except asyncio.CancelledError:
                pass

            self.lastglance_task = None

        await self.radarr.close()

        await super().close()

    # ============================================================
    # Radarr
    # ============================================================

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

        if not isinstance(
            movie,
            dict,
        ):
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

        return mapping.get(
            event_type,
        )

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
                description=(f"**{request['year']}**" if request["year"] else None),
            )

            parent_embed.add_field(
                name="Requested by",
                value=f"<@{request['requester_id']}>",
                inline=True,
            )

            parent_embed.add_field(
                name="Status",
                value=self._status_text(
                    status,
                ),
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

            status_embed = discord.Embed(
                title=f"🎬 {request['title']}",
                description=(f"**{request['year']}**" if request["year"] else None),
            )

            status_embed.add_field(
                name="Status",
                value=self._status_text(
                    status,
                ),
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
                "Discord bot does not have permission to update request %s",
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

    # ============================================================
    # LastGLANCE
    # ============================================================

    async def _register_lastglance_views(
        self,
    ) -> None:
        if self.lastglance_views_registered:
            return

        try:
            document = await asyncio.to_thread(
                load_sync,
            )

        except FileNotFoundError:
            logger.warning(
                "LastGLANCE sync file does not exist yet",
            )

            return

        except Exception:
            logger.exception(
                "Unable to load LastGLANCE sync while registering views",
            )

            return

        data = document.get(
            "data",
            {},
        )

        if not isinstance(
            data,
            dict,
        ):
            logger.warning(
                "LastGLANCE data is invalid",
            )

            return

        chores = data.get(
            "chores",
            [],
        )

        if not isinstance(
            chores,
            list,
        ):
            logger.warning(
                "LastGLANCE chores is not a list",
            )

            return

        registered = 0

        for chore in chores:
            if not isinstance(
                chore,
                dict,
            ):
                continue

            chore_id = get_chore_sync_id(
                chore,
            )

            if not chore_id:
                continue

            view = ChoreView(
                chore_id=chore_id,
                chore_name=chore.get(
                    "name",
                    "Unnamed chore",
                ),
                complete_chore=complete_chore,
            )

            try:
                self.add_view(
                    view,
                )

                registered += 1

            except ValueError:
                logger.debug(
                    "LastGLANCE view already registered for %s",
                    chore_id,
                )

        self.lastglance_views_registered = True

        logger.info(
            "Registered %s LastGLANCE persistent views",
            registered,
        )

    async def _lastglance_loop(
        self,
    ) -> None:
        await self.wait_until_ready()

        while not self.is_closed():
            try:
                await self._process_lastglance()

            except Exception:
                logger.exception(
                    "Unhandled LastGLANCE error",
                )

            await asyncio.sleep(
                settings.lastglance_check_interval_minutes * 60,
            )

    async def _process_lastglance(
        self,
    ) -> None:
        try:
            document = await asyncio.to_thread(
                load_sync,
            )

        except FileNotFoundError:
            logger.warning(
                "LastGLANCE sync file does not exist",
            )

            return

        except Exception:
            logger.exception(
                "Unable to read LastGLANCE sync",
            )

            return

        data = document.get(
            "data",
            {},
        )

        if not isinstance(
            data,
            dict,
        ):
            return

        chores = data.get(
            "chores",
            [],
        )

        categories = data.get(
            "categories",
            [],
        )

        completion_events = data.get(
            "completionEvents",
            [],
        )

        if not isinstance(
            chores,
            list,
        ):
            return

        if not isinstance(
            categories,
            list,
        ):
            categories = []

        if not isinstance(
            completion_events,
            list,
        ):
            completion_events = []

        category_map = {
            category["id"]: category
            for category in categories
            if isinstance(
                category,
                dict,
            )
            and category.get("id")
        }

        now = datetime.now(
            timezone.utc,
        )

        state = self._load_lastglance_state()

        channel = self.get_channel(
            settings.lastglance_channel_id,
        )

        if channel is None:
            channel = await self.fetch_channel(
                settings.lastglance_channel_id,
            )

        if not isinstance(
            channel,
            discord.abc.Messageable,
        ):
            logger.error(
                "LastGLANCE channel is not messageable",
            )

            return

        for chore in chores:
            if not isinstance(
                chore,
                dict,
            ):
                continue

            if not chore.get(
                "notifyWhenOverdue",
                False,
            ):
                continue

            chore_id = get_chore_sync_id(
                chore,
            )

            if not chore_id:
                continue

            due_date = calculate_due_date(
                chore,
                completion_events,
            )

            if due_date is None:
                logger.warning(
                    "Unable to calculate due date for LastGLANCE chore %s",
                    chore.get("name"),
                )

                continue

            if due_date > now:
                continue

            chore_state = state.setdefault(
                chore_id,
                {},
            )

            stored_due_date = parse_datetime(
                chore_state.get(
                    "dueDate",
                ),
            )

            last_notified = parse_datetime(
                chore_state.get(
                    "lastNotifiedAt",
                ),
            )

            if stored_due_date is None or stored_due_date != due_date:
                chore_state["dueDate"] = due_date.isoformat()

                chore_state["lastNotifiedAt"] = None

                last_notified = None

            if last_notified is not None:
                next_notification = last_notified + timedelta(
                    days=settings.lastglance_reminder_interval_days,
                )

                if now < next_notification:
                    continue

            category_path = self._lastglance_category_path(
                chore.get(
                    "categorySyncId",
                ),
                category_map,
            )

            overdue_days = max(
                0,
                (now.date() - due_date.date()).days,
            )

            category_line = ""

            if category_path:
                category_line = f"📁 {category_path}\n"

            cadence = chore.get(
                "targetCadenceDays",
            )

            message = (
                "🔧 **LastGLANCE — Maintenance Due**\n\n"
                f"**{chore.get('name', 'Unnamed chore')}**\n"
                f"{category_line}"
                f"⏰ Due: "
                f"{due_date.strftime('%b %-d, %Y')}\n"
                f"📅 Cadence: Every {cadence} days\n"
                f"⚠️ Status: {overdue_days} "
                f"{'day' if overdue_days == 1 else 'days'} "
                "overdue"
            )

            view = ChoreView(
                chore_id=chore_id,
                chore_name=chore.get(
                    "name",
                    "Unnamed chore",
                ),
                complete_chore=complete_chore,
            )

            sent_message = await channel.send(
                content=message,
                view=view,
            )

            chore_state["lastNotifiedAt"] = now.isoformat()

            chore_state["messageId"] = str(
                sent_message.id,
            )

            chore_state["channelId"] = str(
                settings.lastglance_channel_id,
            )

            self._save_lastglance_state(
                state,
            )

            logger.info(
                "Sent LastGLANCE notification for %s",
                chore.get("name"),
            )

    @staticmethod
    def _lastglance_category_path(
        category_id: str | None,
        categories: dict[
            str,
            dict[str, Any],
        ],
    ) -> str:
        if not category_id:
            return ""

        path: list[str] = []
        visited: set[str] = set()

        current_id = category_id

        while current_id and current_id not in visited:
            visited.add(
                current_id,
            )

            category = categories.get(
                current_id,
            )

            if not category:
                break

            name = category.get(
                "name",
            )

            if name:
                path.insert(
                    0,
                    name,
                )

            current_id = category.get(
                "parentId",
            )

        return " → ".join(path)

    @staticmethod
    def _load_lastglance_state() -> dict[
        str,
        dict[str, Any],
    ]:
        path = Path(
            "/state/lastglance.json",
        )

        if not path.exists():
            return {}

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as file:
                value = json.load(file)

            if isinstance(
                value,
                dict,
            ):
                return value

        except Exception:
            logger.exception(
                "Unable to load LastGLANCE state",
            )

        return {}

    @staticmethod
    def _save_lastglance_state(
        state: dict[
            str,
            dict[str, Any],
        ],
    ) -> None:
        path = Path(
            "/state/lastglance.json",
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp = path.with_suffix(
            ".tmp",
        )

        with temp.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                state,
                file,
                indent=2,
            )

        temp.replace(
            path,
        )
