import hashlib
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(
    "discord-bot.lastglance",
)


DATA_FILE = Path(
    "/data/lastglance-sync.json",
)


MAX_WRITE_RETRIES = 3


def load_sync() -> dict[str, Any]:
    with DATA_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        document = json.load(file)

    if not isinstance(document, dict):
        raise ValueError(
            "LastGLANCE sync document must be an object",
        )

    return document


def _read_sync_bytes() -> tuple[
    bytes,
    dict[str, Any],
]:
    raw = DATA_FILE.read_bytes()

    document = json.loads(
        raw.decode("utf-8"),
    )

    if not isinstance(document, dict):
        raise ValueError(
            "LastGLANCE sync document must be an object",
        )

    return raw, document


def _fingerprint(
    raw: bytes,
) -> str:
    return hashlib.sha256(
        raw,
    ).hexdigest()


def _write_atomic(
    document: dict[str, Any],
) -> None:
    DATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, temp_name = tempfile.mkstemp(
        prefix=".lastglance-sync-",
        suffix=".tmp",
        dir=DATA_FILE.parent,
    )

    temp_path = Path(temp_name)

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                document,
                file,
                indent=2,
                ensure_ascii=False,
            )

            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        temp_path.replace(
            DATA_FILE,
        )

        directory_fd = os.open(
            DATA_FILE.parent,
            os.O_DIRECTORY,
        )

        try:
            os.fsync(
                directory_fd,
            )
        finally:
            os.close(
                directory_fd,
            )

    finally:
        temp_path.unlink(
            missing_ok=True,
        )


def get_chore_sync_id(
    chore: dict[str, Any],
) -> str | None:
    sync_id = chore.get(
        "sync_id",
    )

    if (
        isinstance(
            sync_id,
            str,
        )
        and sync_id
    ):
        return sync_id

    chore_id = chore.get(
        "id",
    )

    if (
        isinstance(
            chore_id,
            str,
        )
        and chore_id
    ):
        return chore_id

    return None


def get_chore(
    document: dict[str, Any],
    chore_id: str,
) -> dict[str, Any] | None:
    data = document.get(
        "data",
    )

    if not isinstance(
        data,
        dict,
    ):
        return None

    chores = data.get(
        "chores",
    )

    if not isinstance(
        chores,
        list,
    ):
        return None

    for chore in chores:
        if not isinstance(
            chore,
            dict,
        ):
            continue

        if get_chore_sync_id(chore) == chore_id:
            return chore

    return None


def parse_datetime(
    value: Any,
) -> datetime | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            ),
        )

    except ValueError:
        return None


def get_latest_completion(
    chore_id: str,
    completion_events: list[dict[str, Any]],
) -> datetime | None:
    latest: datetime | None = None

    for event in completion_events:
        if not isinstance(
            event,
            dict,
        ):
            continue

        if event.get("choreSyncId") != chore_id:
            continue

        completed_at = parse_datetime(
            event.get(
                "completedAt",
            ),
        )

        if completed_at is None:
            continue

        if latest is None or completed_at > latest:
            latest = completed_at

    return latest


def calculate_due_date(
    chore: dict[str, Any],
    completion_events: list[dict[str, Any]],
) -> datetime | None:
    cadence_days = chore.get(
        "targetCadenceDays",
    )

    if not isinstance(
        cadence_days,
        (int, float),
    ):
        return None

    chore_id = get_chore_sync_id(
        chore,
    )

    if chore_id is None:
        return None

    latest_completion = get_latest_completion(
        chore_id,
        completion_events,
    )

    if latest_completion:
        return latest_completion + timedelta(
            days=cadence_days,
        )

    created_at = parse_datetime(
        chore.get(
            "createdAt",
        ),
    )

    if created_at is None:
        return None

    return created_at + timedelta(
        days=cadence_days,
    )


def complete_chore(
    chore_id: str,
    note: str | None = None,
) -> dict[str, Any]:
    for attempt in range(
        1,
        MAX_WRITE_RETRIES + 1,
    ):
        original_raw, document = _read_sync_bytes()

        original_fingerprint = _fingerprint(
            original_raw,
        )

        chore = get_chore(
            document,
            chore_id,
        )

        if chore is None:
            raise ValueError(
                f"Chore does not exist: {chore_id}",
            )

        data = document.get(
            "data",
        )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "LastGLANCE sync document has invalid data",
            )

        completion_events = data.get(
            "completionEvents",
        )

        if not isinstance(
            completion_events,
            list,
        ):
            completion_events = []

            data["completionEvents"] = completion_events

        now = (
            datetime.now(
                timezone.utc,
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

        event = {
            "id": str(
                uuid.uuid4(),
            ),
            "choreSyncId": chore_id,
            "completedAt": now,
            "updatedAt": now,
            "note": note,
            "source": "manual",
            "completedByUserSyncId": None,
        }

        completion_events.append(
            event,
        )

        document.setdefault(
            "schemaVersion",
            1,
        )

        document.setdefault(
            "appId",
            "lastglance",
        )

        document.setdefault(
            "version",
            2,
        )

        document["lastModified"] = now
        document["data"] = data

        current_raw = DATA_FILE.read_bytes()

        if _fingerprint(current_raw) != original_fingerprint:
            logger.warning(
                "LastGLANCE sync changed during completion; retrying (attempt %s/%s)",
                attempt,
                MAX_WRITE_RETRIES,
            )

            continue

        _write_atomic(
            document,
        )

        logger.info(
            "Completed LastGLANCE chore %s",
            chore_id,
        )

        return event

    raise RuntimeError(
        "LastGLANCE sync changed repeatedly while completing chore",
    )
