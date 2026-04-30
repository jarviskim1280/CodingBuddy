from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file so it works regardless of cwd
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_ignore_empty=True,   # don't let empty shell vars shadow .env values
        extra="ignore",
    )

    anthropic_api_key: str = ""
    github_token: str = ""
    github_username: str = ""
    github_org: str = ""

    # Use absolute path so every process (CLI, dashboard, agents) shares the same DB
    database_url: str = f"sqlite:///{Path(__file__).parent.parent / 'codingbuddy.db'}"
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
