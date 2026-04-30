from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    github_token: str = ""
    github_username: str = ""
    github_org: str = ""

    database_url: str = "sqlite:///./codingbuddy.db"
    repo_workspace: Path = Path("/tmp/codingbuddy_repos")
    dashboard_port: int = 8080

    # Claude model to use for all agents
    claude_model: str = "claude-sonnet-4-6"
    # Max review rounds before auto-approve
    max_review_rounds: int = 3

    @property
    def github_owner(self) -> str:
        return self.github_org or self.github_username

    @property
    def mock_github(self) -> bool:
        return not bool(self.github_token)


settings = Settings()
