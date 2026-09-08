import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


logger = logging.getLogger("lastglance-notifier")

DATA_FILE = Path("/data/lastglance-sync.json")
STATE_FILE = Path("/state/state.json")

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))

REMINDER_INTERVAL_DAYS = int(os.getenv("REMINDER_INTERVAL_DAYS", "7"))

TEST_CHORE_ID = os.getenv("TEST_CHORE_ID", "")
TEST_OVERDUE_DAYS = int(os.getenv("TEST_OVERDUE_DAYS", "0"))


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"chores": {}}

    try:
        return load_json(STATE_FILE)
    except (json.JSONDecodeError, OSError):
        logger.exception("Unable to read notifier state")
        return {"chores": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    temp_file.replace(STATE_FILE)


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_date(value: datetime) -> str:
    return value.strftime("%b %-d, %Y")


def days_overdue(due_date: datetime, now: datetime) -> int:
    return max(0, (now.date() - due_date.date()).days)


def build_category_map(
    categories: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {category["id"]: category for category in categories if category.get("id")}


def get_category_path(
    category_id: str | None,
    categories: dict[str, dict[str, Any]],
) -> str:
    if not category_id:
        return ""

    path: list[str] = []
    visited: set[str] = set()

    current_id = category_id

    while current_id and current_id not in visited:
        visited.add(current_id)

        category = categories.get(current_id)

        if not category:
            break

        name = category.get("name")

        if name:
            path.insert(0, name)

        current_id = category.get("parentId")

    return " → ".join(path)


def get_latest_completion(
    chore_id: str,
    completion_events: list[dict[str, Any]],
) -> datetime | None:
    """
    Attempts to identify the latest completion event.

    The exact completion event schema from lastGLANCE still needs
    to be confirmed against an actual completed chore export.
    """

    latest: datetime | None = None

    for event in completion_events:
        event_chore_id = (
            event.get("choreSyncId") or event.get("choreId") or event.get("chore_id")
        )

        if event_chore_id and event_chore_id != chore_id:
            continue

        timestamp = (
            event.get("completedAt")
            or event.get("completed_at")
            or event.get("timestamp")
            or event.get("createdAt")
        )

        completed_at = parse_datetime(timestamp)

        if completed_at is None:
            continue

        if latest is None or completed_at > latest:
            latest = completed_at

    return latest


def calculate_due_date(
    chore: dict[str, Any],
    completion_events: list[dict[str, Any]],
) -> datetime | None:
    cadence_days = chore.get("targetCadenceDays")

    if not isinstance(cadence_days, (int, float)):
        return None

    latest_completion = get_latest_completion(
        chore["id"],
        completion_events,
    )

    if latest_completion:
        return latest_completion + timedelta(days=cadence_days)

    created_at = parse_datetime(chore.get("createdAt"))

    if created_at is None:
        return None

    return created_at + timedelta(days=cadence_days)


def should_notify(
    chore: dict[str, Any],
    due_date: datetime,
    state: dict[str, Any],
    now: datetime,
) -> bool:
    chore_id = chore["id"]

    if due_date > now:
        return False

    chore_state = state.setdefault("chores", {}).setdefault(
        chore_id,
        {},
    )

    last_notified = parse_datetime(chore_state.get("lastNotifiedAt"))

    stored_due_date = parse_datetime(chore_state.get("dueDate"))

    # A new due date means the chore was completed since
    # the previous notification cycle.
    if stored_due_date != due_date:
        chore_state["dueDate"] = due_date.isoformat()
        chore_state["lastNotifiedAt"] = None
        last_notified = None

    if last_notified is None:
        return True

    next_notification = last_notified + timedelta(days=REMINDER_INTERVAL_DAYS)

    return now >= next_notification


def build_message(
    chore: dict[str, Any],
    due_date: datetime,
    category_path: str,
    now: datetime,
) -> str:
    overdue_days = days_overdue(due_date, now)

    category_line = f"📁 Category: {category_path}\n" if category_path else ""

    return (
        "🔧 **LastGLANCE — Maintenance Due**\n\n"
        f"**{chore.get('name', 'Unnamed chore')}**\n"
        f"{category_line}"
        f"⏰ Due: {format_date(due_date)}\n"
        f"📅 Cadence: Every "
        f"{chore.get('targetCadenceDays')} days\n"
        f"⚠️ Status: {overdue_days} "
        f"{'day' if overdue_days == 1 else 'days'} overdue"
    )


def send_discord_message(message: str) -> None:
    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json={
            "content": message,
        },
        timeout=15,
    )

    response.raise_for_status()


def process() -> None:
    if not DATA_FILE.exists():
        logger.warning(
            "LastGLANCE sync file does not exist yet: %s",
            DATA_FILE,
        )
        return

    try:
        document = load_json(DATA_FILE)
    except (json.JSONDecodeError, OSError):
        logger.exception("Unable to read LastGLANCE sync file")
        return

    data = document.get("data", {})

    chores = data.get("chores", [])
    categories = data.get("categories", [])
    completion_events = data.get("completionEvents", [])

    if not isinstance(chores, list):
        logger.warning("LastGLANCE chores is not a list")
        return

    if not isinstance(categories, list):
        categories = []

    if not isinstance(completion_events, list):
        completion_events = []

    category_map = build_category_map(categories)
    state = load_state()

    now = datetime.now(timezone.utc)

    for chore in chores:
        if not isinstance(chore, dict):
            continue

        if not chore.get("notifyWhenOverdue", False):
            continue

        chore_id = chore.get("id")

        if not chore_id:
            continue

        try:
            due_date = calculate_due_date(
                chore,
                completion_events,
            )

            if due_date is None:
                logger.warning(
                    "Unable to calculate due date for chore %s",
                    chore.get("name"),
                )
                continue

            if chore_id == TEST_CHORE_ID and TEST_OVERDUE_DAYS > 0:
                due_date = now - timedelta(days=TEST_OVERDUE_DAYS)

            if not should_notify(
                chore,
                due_date,
                state,
                now,
            ):
                continue

            if not should_notify(
                chore,
                due_date,
                state,
                now,
            ):
                continue

            category_path = get_category_path(
                chore.get("categorySyncId"),
                category_map,
            )

            message = build_message(
                chore,
                due_date,
                category_path,
                now,
            )

            logger.info(
                "Sending Discord notification for %s",
                chore.get("name"),
            )

            send_discord_message(message)

            state["chores"][chore_id]["lastNotifiedAt"] = now.isoformat()

            save_state(state)

        except Exception:
            logger.exception(
                "Failed processing chore %s",
                chore.get("name"),
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=("%(asctime)s %(levelname)s %(name)s: %(message)s"),
    )

    logger.info("Starting LastGLANCE notifier")

    while True:
        try:
            process()
        except Exception:
            logger.exception("Unhandled error during notification cycle")

        time.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
