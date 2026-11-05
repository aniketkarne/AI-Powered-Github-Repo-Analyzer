from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env — the location the README tells users to create it — resolved
# against this file instead of the process cwd, so the tokens are picked up no
# matter where uvicorn is launched from.
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    github_token: str = ""
    openai_api_key: str = ""

    model_config = SettingsConfigDict(env_file=DEFAULT_ENV_FILE, extra="ignore")


def build_settings(env_file=None):
    """Settings factory; `env_file` is overridable for tests and embedders."""
    return Settings(_env_file=DEFAULT_ENV_FILE if env_file is None else env_file)


settings = build_settings()
