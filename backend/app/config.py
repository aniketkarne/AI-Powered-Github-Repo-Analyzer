from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str = ""
    openai_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
