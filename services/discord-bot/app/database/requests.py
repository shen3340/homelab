from typing import Any

from app.database.database import get_connection


def create_movie_request(
    *,
    radarr_movie_id: int,
    tmdb_id: int | None,
    title: str,
    year: int | None,
    discord_guild_id: int,
    discord_channel_id: int,
    discord_message_id: int,
    discord_thread_id: int | None,
    requester_id: int,
    status: str,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO movie_requests (
                radarr_movie_id,
                tmdb_id,
                title,
                year,
                discord_guild_id,
                discord_channel_id,
                discord_message_id,
                discord_thread_id,
                requester_id,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                radarr_movie_id,
                tmdb_id,
                title,
                year,
                discord_guild_id,
                discord_channel_id,
                discord_message_id,
                discord_thread_id,
                requester_id,
                status,
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)


def get_movie_request_by_radarr_id(
    radarr_movie_id: int,
) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM movie_requests
            WHERE radarr_movie_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (radarr_movie_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def update_movie_request_status(
    request_id: int,
    status: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE movie_requests
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                request_id,
            ),
        )

        connection.commit()


def update_movie_request_thread(
    request_id: int,
    thread_id: int,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE movie_requests
            SET
                discord_thread_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                thread_id,
                request_id,
            ),
        )

        connection.commit()
