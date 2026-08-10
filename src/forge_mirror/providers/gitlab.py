"""GitLab provider (REST API v4)."""

from collections.abc import Iterator
from typing import ClassVar

from forge_mirror.providers.base import Provider, Repo

_PROJECTS_PATH = "/api/v4/projects"


class GitLabProvider(Provider):
    """Lists projects via the GitLab REST API (v4)."""

    name = "gitlab"
    https_auth_user = "oauth2"
    probe_path = _PROJECTS_PATH
    probe_params: ClassVar[dict[str, str | int]] = {"membership": "true", "per_page": 1}

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"PRIVATE-TOKEN": token}

    def iter_repos(self) -> Iterator[Repo]:
        items = self._paginate_items(
            _PROJECTS_PATH,
            {
                # Without this, gitlab.com returns every public project on the
                # platform; restrict to projects the token's user belongs to.
                "membership": "true",
                "per_page": 100,
                "statistics": "false",
                "order_by": "id",
                "sort": "asc",
            },
        )
        for item in items:
            yield Repo(
                full_name=str(item["path_with_namespace"]),
                ssh_url=str(item["ssh_url_to_repo"]),
                https_url=str(item["http_url_to_repo"]),
                archived=bool(item.get("archived", False)),
            )
