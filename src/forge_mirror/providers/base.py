"""Provider abstraction shared by all supported forges."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType

import httpx

logger = logging.getLogger(__name__)


def _error_detail(response: httpx.Response) -> str:
    """The forge's own explanation of a failed request, if the body carries one.

    GitLab, GitHub and Forgejo all put it under "message"; anything else is
    passed through as trimmed text, which is what a reverse proxy in front of
    the forge tends to answer with.
    """
    try:
        body = response.json()
    except ValueError:
        return " ".join(response.text.split())[:200]
    if isinstance(body, dict):
        for key in ("message", "error_description", "error"):
            value = body.get(key)  # pyright: ignore[reportUnknownMemberType]
            if isinstance(value, str) and value:
                return value
    return ""


def describe_http_error(exc: httpx.HTTPStatusError) -> str:
    """One line naming the request that failed and what the forge said about it."""
    url = exc.request.url.copy_with(query=None)
    summary = f"{exc.response.status_code} for {exc.request.method} {url}"
    detail = _error_detail(exc.response)
    return f"{summary}: {detail}" if detail else summary


@dataclass(frozen=True)
class Repo:
    """A repository to mirror, in provider-neutral form."""

    full_name: str
    ssh_url: str
    https_url: str
    archived: bool


class Provider(ABC):
    """Base class for forge providers.

    Subclasses implement repository listing and the auth header; the shared
    HTTP client, pagination and authenticated clone-URL construction live here.
    """

    # Userinfo prepended to HTTPS clone URLs, e.g. "oauth2" or "x-access-token".
    https_auth_user: str

    def __init__(self, base_url: str, token: str, timeout: float) -> None:
        self._token = token
        self._client = httpx.Client(
            base_url=base_url,
            headers=self._auth_headers(token),
            timeout=timeout,
            follow_redirects=True,
        )

    @abstractmethod
    def _auth_headers(self, token: str) -> dict[str, str]:
        """HTTP headers authenticating API requests."""

    @abstractmethod
    def iter_repos(self) -> Iterator[Repo]:
        """Iterate over all repositories visible to the token."""

    def clone_url(self, repo: Repo, *, use_ssh: bool) -> str:
        """Clone URL for the repo; for HTTPS the token is embedded."""
        if use_ssh:
            return repo.ssh_url
        scheme, sep, rest = repo.https_url.partition("://")
        if not sep:
            return repo.https_url
        return f"{scheme}://{self.https_auth_user}:{self._token}@{rest}"

    def _paginate_items(
        self,
        path: str,
        params: dict[str, str | int],
    ) -> Iterator[dict[str, object]]:
        """Yield JSON list items across all pages, following RFC 5988 links.

        Both GitLab and GitHub return a Link header with rel="next"; httpx
        exposes it via ``response.links``. The next URL already carries the
        query string, so follow-up requests send no extra params.
        """
        url: str | None = path
        next_params: dict[str, str | int] | None = params
        while url:
            response = self._client.get(url, params=next_params)
            response.raise_for_status()
            yield from response.json()
            link = response.links.get("next")
            url = link["url"] if link else None
            next_params = None

    def __enter__(self) -> "Provider":
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
