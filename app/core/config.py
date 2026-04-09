from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # TTS
    voice_provider: str = "auto"  # auto | elevenlabs | silent
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "Rachel"
    elevenlabs_model: str = "eleven_turbo_v2"

    # Visuals
    pexels_api_key: str = ""

    # YouTube
    youtube_client_secrets_file: str = ""
    youtube_token_file: str = ""
    youtube_privacy: str = "private"

    # Storage
    storage_backend: str = "local"
    storage_local_dir: str = "./storage"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Infra
    database_url: str = "postgresql+psycopg://shorts:shorts@localhost:5432/shorts"
    redis_url: str = "redis://localhost:6379/0"

    log_level: str = "INFO"
    env: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
