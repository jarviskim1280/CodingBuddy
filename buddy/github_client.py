"""GitHub API wrapper — falls back to a mock when no token is configured."""
import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from buddy.config import settings


@dataclass
class PullRequest:
    number: int
    url: str
    title: str
    head: str
    base: str = "main"
    diff: str = ""


@dataclass
class MockGitHubClient:
    """Local-only client: creates bare git repos and simulates PRs."""

    workspace: Path = field(default_factory=lambda: settings.repo_workspace)
    _pr_counter: int = 0
    _prs: dict = field(default_factory=dict)

    def __post_init__(self):
        self.workspace.mkdir(parents=True, exist_ok=True)

    def create_repo(self, name: str, description: str = "") -> str:
        repo_dir = self.workspace / "remotes" / name
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", str(repo_dir)], check=True, capture_output=True)
        # create a working clone we can push to
        clone_dir = self.workspace / "clones" / name
        if clone_dir.exists():
            import shutil
            shutil.rmtree(clone_dir)
        subprocess.run(
            ["git", "clone", str(repo_dir), str(clone_dir)],
            check=True, capture_output=True,
        )
        # seed with empty commit so main exists
        subprocess.run(["git", "-C", str(clone_dir), "config", "user.email", "buddy@local"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dir), "config", "user.name", "CodingBuddy"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dir), "commit", "--allow-empty", "-m", "init"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dir), "push", "origin", "main"], capture_output=True)
        return f"file://{repo_dir}"

    def clone_url(self, repo_url: str) -> str:
        return repo_url  # already a local path

    def create_pr(self, repo_url: str, head: str, base: str, title: str, body: str) -> PullRequest:
        self._pr_counter += 1
        pr = PullRequest(
            number=self._pr_counter,
            url=f"mock://pr/{self._pr_counter}",
            title=title,
            head=head,
            base=base,
        )
        self._prs[self._pr_counter] = pr
        return pr

    def get_pr_diff(self, repo_url: str, pr: PullRequest, local_path: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(local_path), "diff", f"origin/{pr.base}...{pr.head}"],
            capture_output=True, text=True,
        )
        return result.stdout[:8000]  # cap diff size

    def post_review_comment(self, repo_url: str, pr: PullRequest, body: str) -> None:
        print(f"[mock] PR#{pr.number} review comment:\n{body[:200]}")

    def merge_pr(self, repo_url: str, pr: PullRequest, local_path: Path) -> None:
        subprocess.run(
            ["git", "-C", str(local_path), "checkout", pr.base],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(local_path), "merge", "--no-ff", pr.head, "-m", f"Merge PR #{pr.number}: {pr.title}"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(local_path), "push", "origin", pr.base],
            capture_output=True,
        )

    def repo_exists(self, name: str) -> bool:
        return (self.workspace / "remotes" / name).exists()


class RealGitHubClient:
    """GitHub API client via httpx + PyGithub for PR ops."""

    def __init__(self):
        from github import Github
        self._gh = Github(settings.github_token)
        self._owner = settings.github_owner
        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github.v3.diff",
            }
        )

    def create_repo(self, name: str, description: str = "") -> str:
        if settings.github_org:
            org = self._gh.get_organization(settings.github_org)
            repo = org.create_repo(name, description=description, private=True, auto_init=True)
        else:
            user = self._gh.get_user()
            repo = user.create_repo(name, description=description, private=True, auto_init=True)
        return repo.clone_url

    def clone_url(self, repo_url: str) -> str:
        # inject token for https auth
        return repo_url.replace("https://", f"https://{settings.github_token}@")

    def create_pr(self, repo_url: str, head: str, base: str, title: str, body: str) -> PullRequest:
        repo_name = self._repo_name_from_url(repo_url)
        repo = self._gh.get_repo(repo_name)
        pr = repo.create_pull(title=title, body=body, head=head, base=base)
        return PullRequest(number=pr.number, url=pr.html_url, title=title, head=head, base=base)

    def get_pr_diff(self, repo_url: str, pr: PullRequest, local_path: Path) -> str:
        repo_name = self._repo_name_from_url(repo_url)
        resp = self._http.get(
            f"https://api.github.com/repos/{repo_name}/pulls/{pr.number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        return resp.text[:8000]

    def post_review_comment(self, repo_url: str, pr: PullRequest, body: str) -> None:
        repo_name = self._repo_name_from_url(repo_url)
        repo = self._gh.get_repo(repo_name)
        gh_pr = repo.get_pull(pr.number)
        gh_pr.create_issue_comment(body)

    def merge_pr(self, repo_url: str, pr: PullRequest, local_path: Path) -> None:
        repo_name = self._repo_name_from_url(repo_url)
        repo = self._gh.get_repo(repo_name)
        gh_pr = repo.get_pull(pr.number)
        gh_pr.merge(merge_method="squash")

    def _repo_name_from_url(self, url: str) -> str:
        # https://github.com/owner/repo.git -> owner/repo
        parts = url.rstrip("/").rstrip(".git").split("/")
        return f"{parts[-2]}/{parts[-1]}"


def get_github_client():
    if settings.mock_github:
        return MockGitHubClient()
    return RealGitHubClient()
