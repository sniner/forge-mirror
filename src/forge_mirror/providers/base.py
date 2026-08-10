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


# Answered by a forge that serves the API but will not let this token read.
_REFUSED = (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN)


@dataclass(frozen=True)
class ProbeResult:
    """What a forge answered when asked whether the repositories are its own."""

    accepted: bool
    refused: bool
    status: int


class Provider(ABC):
    """Base class for forge providers.

    Subclasses implement repository listing and the auth header; the shared
    HTTP client, pagination and authenticated clone-URL construction live here.
    """

    # Identifier used by --provider and in messages.
    name: ClassVar[str]

    # Userinfo prepended to HTTPS clone URLs, e.g. "oauth2" or "x-access-token".
    https_auth_user: ClassVar[str]

    # A one-page listing request, used to recognise the forge. Only this forge's
    # API serves the path, and only a token that may read repositories gets a
    # list back — which is what iter_repos needs, nothing more and nothing less.
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
        """Build this provider for a run, with the URL it actually talks to."""
        return cls(cls.normalize_url(config.base_url), config.token, config.timeout)

    @classmethod
    def normalize_url(cls, url: str) -> str:
        """The API base URL this provider uses for a URL as the user gave it."""
        return url

    @abstractmethod
    def _auth_headers(self, token: str) -> dict[str, str]:
        """HTTP headers authenticating API requests."""

    @abstractmethod
    def iter_repos(self) -> Iterator[Repo]:
        """Iterate over all repositories visible to the token."""

    def probe(self) -> ProbeResult:
        """Ask whether this forge answers at the configured URL for this token.

        A JSON list back means both, so a positive probe is a promise that
        iter_repos will work rather than a guess about the software. Transport
        errors are not caught: an unreachable host is the same for every forge
        and should be reported once, not tried three times.
        """
        response = self._client.get(self.probe_path, params=self.probe_params)
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            # Anything but JSON under an API path is the web front end or a
            # proxy talking, not this forge's API. gitlab.com answers 403 with
            # an HTML page for every route it does not serve, and taking that
            # for a refusal would make it look like all three forges at once.
            return ProbeResult(accepted=False, refused=False, status=status)
        if status == httpx.codes.OK:
            return ProbeResult(
                accepted=isinstance(body, list), refused=False, status=status
            )
        return ProbeResult(accepted=False, refused=status in _REFUSED, status=status)

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
