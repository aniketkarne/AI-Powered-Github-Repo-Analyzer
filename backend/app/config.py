from pydantic import BaseSettings

class Settings(BaseSettings):
    github_token: str
    openai_api_key: str
    redis_url: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"

settings = Settings()