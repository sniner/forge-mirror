"""GitHub provider (REST API v3)."""

import re
from collections.abc import Iterator
from typing import ClassVar, Self

from forge_mirror.config import Config
from forge_mirror.providers.base import Provider, Repo

_USER_REPOS_PATH = "/user/repos"

# github.com serves its API from a separate host, unlike Enterprise, which uses
# /api/v3 on the web host — so only the public web host is rewritten.
_WEB_HOST = re.compile(r"^(https?://)(www\.)?github\.com/?$", re.IGNORECASE)


class GitHubProvider(Provider):
    """Lists repositories via the GitHub REST API."""

    name = "github"
    https_auth_user = "x-access-token"
    probe_path = _USER_REPOS_PATH
    probe_params: ClassVar[dict[str, str | int]] = {"per_page": 1}

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        owner: str | None = None,
    ) -> None:
        super().__init__(base_url, token, timeout)
        self._owner = owner

    @classmethod
    def from_config(cls, config: Config) -> Self:
        return cls(
            cls.normalize_url(config.base_url),
            config.token,
            config.timeout,
            config.owner,
        )

    @classmethod
    def normalize_url(cls, url: str) -> str:
        return _WEB_HOST.sub(r"\1api.github.com", url)

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repos_endpoint(self) -> tuple[str, dict[str, str | int]]:
        """Resolve the listing endpoint and query params for the configured owner."""
        if self._owner is None:
            return _USER_REPOS_PATH, {
                "per_page": 100,
                "affiliation": "owner,collaborator,organization_member",
                "sort": "full_name",
            }
        response = self._client.get(f"/users/{self._owner}")
        response.raise_for_status()
        if response.json().get("type") == "Organization":
            return f"/orgs/{self._owner}/repos", {"per_page": 100, "type": "all"}
        return f"/users/{self._owner}/repos", {"per_page": 100, "type": "owner"}

    def iter_repos(self) -> Iterator[Repo]:
        path, params = self._repos_endpoint()
        for item in self._paginate_items(path, params):
            yield Repo(
                full_name=str(item["full_name"]),
                ssh_url=str(item["ssh_url"]),
                https_url=str(item["clone_url"]),
                archived=bool(item.get("archived", False)),
            )
