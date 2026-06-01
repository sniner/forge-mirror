"""Minimal GitLab API client for listing projects."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

_PER_PAGE = 100


@dataclass(frozen=True)
class Project:
    """The fields of a GitLab project relevant for mirroring."""

    path_with_namespace: str
    ssh_url_to_repo: str
    http_url_to_repo: str
    archived: bool

    @classmethod
    def from_api(cls, data: dict[str, object]) -> "Project":
        return cls(
            path_with_namespace=str(data["path_with_namespace"]),
            ssh_url_to_repo=str(data["ssh_url_to_repo"]),
            http_url_to_repo=str(data["http_url_to_repo"]),
            archived=bool(data.get("archived", False)),
        )


class ProjectSource(Protocol):
    """Supplies the projects to mirror (implemented by GitLabClient)."""

    def iter_projects(self) -> Iterator[Project]: ...


class GitLabClient:
    """Wraps an httpx.Client for the GitLab REST API (v4)."""

    def __init__(self, gitlab_url: str, token: str, timeout: float) -> None:
        self._client = httpx.Client(
            base_url=gitlab_url,
            headers={"PRIVATE-TOKEN": token},
            timeout=timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> "GitLabClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def iter_projects(self) -> Iterator[Project]:
        """Iterate over all projects visible to the token.

        Follows GitLab's offset pagination via the X-Next-Page header.
        """
        page = 1
        while page:
            response = self._client.get(
                "/api/v4/projects",
                params={
                    "page": page,
                    "per_page": _PER_PAGE,
                    "statistics": "false",
                    "order_by": "id",
                    "sort": "asc",
                },
            )
            response.raise_for_status()

            for item in response.json():
                yield Project.from_api(item)

            next_page = response.headers.get("X-Next-Page", "")
            page = int(next_page) if next_page else 0
