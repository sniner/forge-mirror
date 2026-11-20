"""Provider abstraction shared by all supported forges."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import ClassVar, Self

import httpx

from forge_mirror.config import Config

logger = logging.getLogger(__name__)


def _error_detail(response: httpx.Response) -> str:
    """The error message in the body of a failed response, if there is one.

    GitLab, GitHub and Forgejo put it under "message". A body that is not JSON,
    typically from a reverse proxy in front of the forge, is returned as trimmed
    text.
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
    """One line with the failed request and the error message of the response."""
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


@dataclass(frozen=True)
class Credentials:
    """User name and password git sends to the forge over HTTPS."""

    username: str
    password: str


# Status codes of a forge API that rejects the token.
_REFUSED = (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN)


@dataclass(frozen=True)
class ProbeResult:
    """Result of a probe request to the listing endpoint of one forge."""

    accepted: bool
    refused: bool
    status: int


class Provider(ABC):
    """Base class for forge providers.

    Subclasses implement repository listing and the auth header; the shared
    HTTP client, pagination and the git credentials live here.
    """

    # Identifier used by --provider and in messages.
    name: ClassVar[str]

    # User name git sends with the token over HTTPS, e.g. "oauth2" or
    # "x-access-token".
    https_auth_user: ClassVar[str]

    # A one-page listing request used for detection. Only this forge's API serves
    # the path, and it returns a list only for a token that may list
    # repositories, which is what iter_repos needs.
    probe_path: ClassVar[str]
    probe_params: ClassVar[dict[str, str | int]]

    def __init__(self, base_url: str, token: str, timeout: float) -> None:
        self.base_url = base_url
        self._token = token
        self._client = httpx.Client(
            base_url=base_url,
            headers=self._auth_headers(token),
            timeout=timeout,
            follow_redirects=True,
        )

    @classmethod
    def from_config(cls, config: Config) -> Self:
        """Build this provider for a run, with the normalized API URL."""
        return cls(cls.normalize_url(config.base_url), config.token, config.timeout)

    @classmethod
    def normalize_url(cls, url: str) -> str:
        """The API base URL for the URL the user gave."""
        return url

    @abstractmethod
    def _auth_headers(self, token: str) -> dict[str, str]:
        """HTTP headers authenticating API requests."""

    @abstractmethod
    def iter_repos(self) -> Iterator[Repo]:
        """Iterate over all repositories visible to the token."""

    def probe(self) -> ProbeResult:
        """Request one listing page to test whether this forge is at the URL.

        A JSON list means that this forge serves the URL and accepts the token,
        so iter_repos will work after a positive probe. Transport errors are not
        caught: an unreachable host fails the same way for every forge and is
        reported once instead of three times.
        """
        response = self._client.get(self.probe_path, params=self.probe_params)
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            # A body that is not JSON comes from a web front end or a proxy, not
            # from this forge's API. gitlab.com returns 403 with an HTML page for
            # every path it does not serve; counting that as a rejected token
            # would match all three forges.
            return ProbeResult(accepted=False, refused=False, status=status)
        if status == httpx.codes.OK:
            return ProbeResult(
                accepted=isinstance(body, list), refused=False, status=status
            )
        return ProbeResult(accepted=False, refused=status in _REFUSED, status=status)

    def credentials(self) -> Credentials:
        """The token in the form git sends it over HTTPS."""
        return Credentials(username=self.https_auth_user, password=self._token)

    def _paginate_items(
        self,
        path: str,
        params: dict[str, str | int],
    ) -> Iterator[dict[str, object]]:
        """Yield JSON list items across all pages, following RFC 5988 links.

        Both GitLab and GitHub return a Link header with rel="next"; httpx
        exposes it via ``response.links``. The next URL already contains the
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

    def __enter__(self) -> Self:
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
