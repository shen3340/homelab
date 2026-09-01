import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RadarrError(Exception):
    """Raised when Radarr cannot fulfill a request."""


class RadarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
    ):
        self.base_url = base_url.rstrip("/")

        self.headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
        }

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=httpx.Timeout(
                connect=5.0,
                read=30.0,
                write=30.0,
                pool=5.0,
            ),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def health(self) -> bool:
        try:
            response = await self.client.get(
                "/api/v3/system/status",
            )

            response.raise_for_status()

            return True

        except httpx.HTTPError as exc:
            logger.error(
                "Radarr health check failed: %s",
                exc,
            )

            return False

    async def search(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []

        try:
            response = await self.client.get(
                "/api/v3/movie/lookup",
                params={
                    "term": query.strip(),
                },
            )

            response.raise_for_status()

        except httpx.HTTPError as exc:
            logger.error(
                "Radarr movie search failed: %s",
                exc,
            )

            raise RadarrError("Unable to communicate with Radarr.") from exc

        data = response.json()

        if not isinstance(data, list):
            raise RadarrError("Radarr returned an unexpected response.")

        return data

    async def get_movie(
        self,
        tmdb_id: int,
    ) -> dict[str, Any]:
        try:
            response = await self.client.get(
                "/api/v3/movie/lookup/tmdb",
                params={
                    "tmdbId": tmdb_id,
                },
            )

            response.raise_for_status()

        except httpx.HTTPError as exc:
            logger.error(
                "Radarr movie lookup failed for TMDB ID %s: %s",
                tmdb_id,
                exc,
            )

            raise RadarrError("Unable to retrieve movie details from Radarr.") from exc

        data = response.json()

        if not isinstance(data, dict):
            raise RadarrError("Radarr returned unexpected movie data.")

        return data

    async def get_root_folders(self) -> list[dict[str, Any]]:
        try:
            response = await self.client.get(
                "/api/v3/rootfolder",
            )

            response.raise_for_status()

        except httpx.HTTPError as exc:
            logger.error(
                "Radarr root folder request failed: %s",
                exc,
            )

            raise RadarrError("Unable to retrieve Radarr root folders.") from exc

        data = response.json()

        if not isinstance(data, list):
            raise RadarrError("Radarr returned unexpected root folder data.")

        return data

    async def get_quality_profiles(
        self,
    ) -> list[dict[str, Any]]:
        try:
            response = await self.client.get(
                "/api/v3/qualityprofile",
            )

            response.raise_for_status()

        except httpx.HTTPError as exc:
            logger.error(
                "Radarr quality profile request failed: %s",
                exc,
            )

            raise RadarrError("Unable to retrieve Radarr quality profiles.") from exc

        data = response.json()

        if not isinstance(data, list):
            raise RadarrError("Radarr returned unexpected quality profile data.")

        return data

    async def add_movie(
        self,
        movie: dict[str, Any],
    ) -> dict[str, Any]:
        root_folders = await self.get_root_folders()

        if not root_folders:
            raise RadarrError("Radarr has no configured root folders.")

        quality_profiles = await self.get_quality_profiles()

        if not quality_profiles:
            raise RadarrError("Radarr has no configured quality profiles.")

        root_folder = root_folders[0]
        quality_profile = quality_profiles[0]

        movie_payload = {
            **movie,
            "rootFolderPath": root_folder["path"],
            "qualityProfileId": quality_profile["id"],
            "monitored": True,
            "addOptions": {
                "searchForMovie": True,
            },
        }

        # Radarr does not need lookup-only fields when creating
        # a movie. These can cause validation issues.
        movie_payload.pop(
            "id",
            None,
        )

        try:
            response = await self.client.post(
                "/api/v3/movie",
                json=movie_payload,
            )

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Radarr failed to add movie: %s",
                exc.response.text,
            )

            raise RadarrError("Radarr rejected the movie request.") from exc

        except httpx.HTTPError as exc:
            logger.error(
                "Radarr movie add failed: %s",
                exc,
            )

            raise RadarrError("Unable to communicate with Radarr.") from exc

        data = response.json()

        if not isinstance(data, dict):
            raise RadarrError("Radarr returned unexpected movie data.")

        logger.info(
            "Movie added to Radarr: %s (%s)",
            data.get("title"),
            data.get("year"),
        )

        return data
