from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    discord_token: str
    discord_guild_id: int

    radarr_url: str
    radarr_api_key: str


settings = Settings()
