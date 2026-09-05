import os
from datetime import datetime

import psycopg

DATABASE_HOST = os.environ["DATABASE_HOST"]
DATABASE_NAME = os.environ["DATABASE_NAME"]
DATABASE_USER = os.environ["DATABASE_USER"]
DATABASE_PASSWORD = os.environ["DATABASE_PASSWORD"]


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=DATABASE_HOST,
        dbname=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD,
    )


def initialize_auth_tables() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS spotify_auth (
                id INTEGER PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS spotify_oauth_state (
                state TEXT PRIMARY KEY,
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )


def save_spotify_tokens(
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO spotify_auth (
                id,
                access_token,
                refresh_token,
                expires_at
            )
            VALUES (1, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at
            """,
            (access_token, refresh_token, expires_at),
        )


def get_spotify_tokens() -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                access_token,
                refresh_token,
                expires_at
            FROM spotify_auth
            WHERE id = 1
            """
        ).fetchone()

    if row is None:
        return None

    return {
        "access_token": row[0],
        "refresh_token": row[1],
        "expires_at": row[2],
    }


def update_spotify_access_token(
    access_token: str,
    expires_at: datetime,
    refresh_token: str | None = None,
) -> None:
    with get_connection() as connection:
        if refresh_token is None:
            connection.execute(
                """
                UPDATE spotify_auth
                SET
                    access_token = %s,
                    expires_at = %s
                WHERE id = 1
                """,
                (access_token, expires_at),
            )
        else:
            connection.execute(
                """
                UPDATE spotify_auth
                SET
                    access_token = %s,
                    refresh_token = %s,
                    expires_at = %s
                WHERE id = 1
                """,
                (access_token, refresh_token, expires_at),
            )


def save_oauth_state(
    state: str,
    expires_at: datetime,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO spotify_oauth_state (
                state,
                expires_at
            )
            VALUES (%s, %s)
            """,
            (state, expires_at),
        )


def consume_oauth_state(state: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            DELETE FROM spotify_oauth_state
            WHERE state = %s
              AND expires_at > NOW()
            RETURNING state
            """,
            (state,),
        ).fetchone()

    return row is not None


def get_tag(tag_uid: str):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                t.id,
                t.tag_uid,
                a.artist,
                a.title,
                t.album_id,
                t.enabled,
                a.spotify_uri,
                a.navidrome_id
            FROM tags t
            JOIN albums a
                ON a.id = t.album_id
            WHERE t.tag_uid = %s
            """,
            (tag_uid,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "tag_uid": row[1],
        "artist": row[2],
        "title": row[3],
        "album_id": row[4],
        "enabled": row[5],
        "spotify_uri": row[6],
        "navidrome_id": row[7],
    }


def get_spotify_device() -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                device_id,
                device_name
            FROM spotify_settings
            WHERE id = 1
            """
        ).fetchone()

    if row is None:
        return None

    return {
        "device_id": row[0],
        "device_name": row[1],
    }


def save_spotify_device(
    device_id: str,
    device_name: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO spotify_settings (
                id,
                device_id,
                device_name
            )
            VALUES (1, %s, %s)
            ON CONFLICT (id)
            DO UPDATE SET
                device_id = EXCLUDED.device_id,
                device_name = EXCLUDED.device_name
            """,
            (device_id, device_name),
        )


def get_all_tags():
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                t.id,
                t.tag_uid,
                a.artist,
                a.title,
                t.album_id,
                t.enabled
            FROM tags t
            JOIN albums a
                ON a.id = t.album_id
            ORDER BY t.id
            """
        ).fetchall()

    return [
        {
            "id": row[0],
            "tag_uid": row[1],
            "artist": row[2],
            "title": row[3],
            "album_id": row[4],
            "enabled": row[5],
        }
        for row in rows
    ]


def create_album(
    artist: str,
    title: str,
    spotify_id: str | None = None,
    spotify_uri: str | None = None,
    navidrome_id: str | None = None,
) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO albums (
                artist,
                title,
                spotify_id,
                spotify_uri,
                navidrome_id
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                artist,
                title,
                spotify_id,
                spotify_uri,
                navidrome_id,
            ),
        ).fetchone()

    return row[0]


def get_album_by_spotify_id(
    spotify_id: str,
) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                artist,
                title,
                spotify_id,
                spotify_uri,
                navidrome_id
            FROM albums
            WHERE spotify_id = %s
            """,
            (spotify_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "artist": row[1],
        "title": row[2],
        "spotify_id": row[3],
        "spotify_uri": row[4],
        "navidrome_id": row[5],
    }


def create_tag(
    tag_uid: str,
    album_id: int,
) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO tags (
                tag_uid,
                album_id
            )
            VALUES (%s, %s)
            RETURNING id
            """,
            (
                tag_uid,
                album_id,
            ),
        ).fetchone()

    if row is None:
        raise ValueError("Unable to create tag")

    return row[0]


def delete_tag(tag_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            DELETE FROM tags
            WHERE id = %s
            RETURNING id
            """,
            (tag_id,),
        ).fetchone()

    return row is not None


def update_tag(
    tag_id: int,
    tag_uid: str,
    album_id: int,
    enabled: bool,
) -> None:
    with get_connection() as connection:
        row = connection.execute(
            """
            UPDATE tags
            SET
                tag_uid = %s,
                album_id = %s,
                enabled = %s
            WHERE id = %s
            RETURNING id
            """,
            (
                tag_uid,
                album_id,
                enabled,
                tag_id,
            ),
        ).fetchone()

    if row is None:
        raise ValueError("Tag not found")


def get_all_albums() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                artist,
                title,
                spotify_id,
                spotify_uri,
                navidrome_id
            FROM albums
            ORDER BY artist, title
            """
        ).fetchall()

    return [
        {
            "id": row[0],
            "artist": row[1],
            "title": row[2],
            "spotify_id": row[3],
            "spotify_uri": row[4],
            "navidrome_id": row[5],
        }
        for row in rows
    ]


def update_album(
    album_id: int,
    artist: str,
    title: str,
    spotify_uri: str | None,
    navidrome_id: str | None,
) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            UPDATE albums
            SET
                artist = %s,
                title = %s,
                spotify_uri = %s,
                navidrome_id = %s
            WHERE id = %s
            RETURNING id
            """,
            (
                artist,
                title,
                spotify_uri,
                navidrome_id,
                album_id,
            ),
        ).fetchone()

    return row is not None


def delete_album(album_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            DELETE FROM albums
            WHERE id = %s
            RETURNING id
            """,
            (album_id,),
        ).fetchone()

    return row is not None
