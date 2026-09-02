import os

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


def get_tag(tag_uid: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                tags.id,
                tags.tag_uid,
                tags.name,
                albums.artist,
                albums.title,
                albums.spotify_uri,
                albums.navidrome_id
            FROM tags
            LEFT JOIN albums
                ON albums.id = tags.album_id
            WHERE tags.tag_uid = %s
              AND tags.enabled = TRUE
            """,
            (tag_uid,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "tag_uid": row[1],
        "name": row[2],
        "artist": row[3],
        "title": row[4],
        "spotify_uri": row[5],
        "navidrome_id": row[6],
    }
