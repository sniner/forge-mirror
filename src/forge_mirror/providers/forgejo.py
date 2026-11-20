"""Forgejo provider (Gitea-compatible REST API v1)."""

from collections.abc import Iterator
from typing import ClassVar

from forge_mirror.providers.base import Provider, Repo

# An instance limits the page size to its max_response_items setting, 50 by
# default. Pagination follows the Link header either way.
_PAGE_SIZE = 50

_REPOS_PATH = "/api/v1/user/repos"


class ForgejoProvider(Provider):
    """Lists repositories via the Forgejo REST API (v1), as Gitea serves it too."""

    name = "forgejo"

    # Forgejo accepts git over HTTPS with any user name if the basic-auth
    # password is a valid access token.
    https_auth_user = "token"

    probe_path = _REPOS_PATH
    probe_params: ClassVar[dict[str, str | int]] = {"limit": 1}

    def _auth_headers(self, token: str) -> dict[str, str]:
        # Forgejo expects the scheme name "token" here, not "Bearer".
        return {"Authorization": f"token {token}"}

    def iter_repos(self) -> Iterator[Repo]:
        items = self._paginate_items(_REPOS_PATH, {"limit": _PAGE_SIZE})
        for item in items:
            yield Repo(
                full_name=str(item["full_name"]),
                ssh_url=str(item["ssh_url"]),
                https_url=str(item["clone_url"]),
                archived=bool(item.get("archived", False)),
            )
