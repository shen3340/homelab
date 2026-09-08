from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    discord_token: str
    discord_guild_id: int
    lastglance_channel_id: int

    lastglance_check_interval_minutes: int = 60
    lastglance_reminder_interval_days: int = 7

    radarr_url: str
    radarr_api_key: str


settings = Settings()
