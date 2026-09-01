import sqlite3
from pathlib import Path

DATABASE_PATH = Path("/data/discord-bot.db")


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        DATABASE_PATH,
    )

    connection.row_factory = sqlite3.Row

    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS movie_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                radarr_movie_id INTEGER NOT NULL,
                tmdb_id INTEGER,
                title TEXT NOT NULL,
                year INTEGER,
                discord_guild_id INTEGER NOT NULL,
                discord_channel_id INTEGER NOT NULL,
                discord_message_id INTEGER NOT NULL,
                discord_thread_id INTEGER,
                requester_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Existing databases need this column added.
        columns = connection.execute(
            """
            PRAGMA table_info(movie_requests)
            """
        ).fetchall()

        column_names = {column["name"] for column in columns}

        if "discord_thread_id" not in column_names:
            connection.execute(
                """
                ALTER TABLE movie_requests
                ADD COLUMN discord_thread_id INTEGER
                """
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_movie_requests_radarr_id
            ON movie_requests(radarr_movie_id)
            """
        )

        connection.commit()
