"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings with .env file support."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite+aiosqlite:///./auto_deploy.db"
    secret_key: str = "change-me-to-a-random-secret-string"
    app_name: str = "Auto Deploy"
    debug: bool = False
    app_password: str = ""  # empty = auth disabled (local dev)


settings = Settings()
