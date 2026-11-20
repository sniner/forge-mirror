from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import respx

from forge_mirror.config import AUTO, Config
from forge_mirror.providers import create_provider
from forge_mirror.providers.forgejo import ForgejoProvider
from forge_mirror.providers.github import GitHubProvider
from forge_mirror.providers.gitlab import GitLabProvider

URL = "https://forge.example"

GITLAB_PROBE = f"{URL}/api/v4/projects"
GITHUB_PROBE = f"{URL}/user/repos"
FORGEJO_PROBE = f"{URL}/api/v1/user/repos"

_BASE = Config(
    provider=AUTO,
    base_url=URL,
    token="t",
    target_dir=Path("/d"),
    owner=None,
    list_only=False,
    dry_run=False,
    use_ssh=False,
    include_archived=False,
    prune=False,
    prune_limit=10,
    jobs=4,
    timeout=10.0,
)


def make_config(
    *,
    provider: str = AUTO,
    base_url: str = URL,
    owner: str | None = None,
) -> Config:
    return replace(_BASE, provider=provider, base_url=base_url, owner=owner)


def mock_probes(
    *,
    gitlab: httpx.Response,
    github: httpx.Response,
    forgejo: httpx.Response,
) -> dict[str, respx.Route]:
    """Answer every forge's listing endpoint, so each probe gets a real reply."""
    return {
        "gitlab": respx.get(GITLAB_PROBE).mock(return_value=gitlab),
        "github": respx.get(GITHUB_PROBE).mock(return_value=github),
        "forgejo": respx.get(FORGEJO_PROBE).mock(return_value=forgejo),
    }


def not_found() -> httpx.Response:
    return httpx.Response(404, json={"message": "Not Found"})


@respx.mock
def test_detects_the_forge_that_lists_repositories() -> None:
    mock_probes(
        gitlab=not_found(),
        github=not_found(),
        # An empty listing still proves the token may read repositories.
        forgejo=httpx.Response(200, json=[]),
    )

    with create_provider(make_config()) as provider:
        assert isinstance(provider, ForgejoProvider)


@respx.mock
def test_each_forge_is_asked_with_its_own_authentication() -> None:
    routes = mock_probes(
        gitlab=not_found(), github=not_found(), forgejo=httpx.Response(200, json=[])
    )

    with create_provider(make_config()):
        pass

    assert routes["gitlab"].calls.last.request.headers["PRIVATE-TOKEN"] == "t"
    assert routes["github"].calls.last.request.headers["Authorization"] == "Bearer t"
    assert routes["forgejo"].calls.last.request.headers["Authorization"] == "token t"


@respx.mock
def test_stops_asking_once_a_forge_answers() -> None:
    routes = mock_probes(
        gitlab=httpx.Response(200, json=[]), github=not_found(), forgejo=not_found()
    )

    with create_provider(make_config()) as provider:
        assert isinstance(provider, GitLabProvider)

    assert not routes["github"].called
    assert not routes["forgejo"].called


@respx.mock
def test_a_forge_that_refuses_the_token_is_named() -> None:
    mock_probes(
        gitlab=not_found(),
        github=not_found(),
        forgejo=httpx.Response(403, json={"message": "missing scope"}),
    )

    with pytest.raises(ValueError, match="forgejo") as caught:
        create_provider(make_config())

    assert "rejects the token" in str(caught.value)


@respx.mock
def test_an_html_refusal_is_the_web_front_end_not_the_forge() -> None:
    # gitlab.com to the letter: its API says 401 in JSON, while every route it
    # does not serve is answered by the web front end with a 403 HTML page.
    wall = httpx.Response(403, html="<html><body>Forbidden</body></html>")
    mock_probes(
        gitlab=httpx.Response(401, json={"message": "401 Unauthorized"}),
        github=wall,
        forgejo=wall,
    )

    with pytest.raises(ValueError) as caught:
        create_provider(make_config())

    message = str(caught.value)
    assert f"{URL} is gitlab, but rejects the token" in message
    assert "github" not in message
    assert "forgejo" not in message


@respx.mock
def test_several_refusals_do_not_claim_an_identity() -> None:
    refusal = httpx.Response(401, json={"message": "denied"})
    mock_probes(gitlab=refusal, github=refusal, forgejo=refusal)

    with pytest.raises(ValueError, match="rejects the token") as caught:
        create_provider(make_config())

    assert not any(name in str(caught.value) for name in ("gitlab", "github", "forgejo"))


@respx.mock
def test_no_forge_at_all_points_at_the_url() -> None:
    mock_probes(gitlab=not_found(), github=not_found(), forgejo=not_found())

    with pytest.raises(ValueError, match="No GitLab, GitHub or Forgejo API") as caught:
        create_provider(make_config())

    assert URL in str(caught.value)


@respx.mock
def test_a_200_that_is_not_a_listing_counts_for_nothing() -> None:
    # What a reverse proxy or a login page in front of the forge tends to answer.
    page = httpx.Response(200, html="<html><body>Sign in</body></html>")
    mock_probes(gitlab=page, github=page, forgejo=page)

    with pytest.raises(ValueError, match="No GitLab, GitHub or Forgejo API"):
        create_provider(make_config())


@respx.mock
def test_github_is_asked_on_the_api_host_the_others_on_the_url_as_given() -> None:
    web = "https://github.com"
    respx.get(f"{web}/api/v4/projects").mock(return_value=not_found())
    respx.get(f"{web}/api/v1/user/repos").mock(return_value=not_found())
    api = respx.get("https://api.github.com/user/repos").mock(
        return_value=httpx.Response(200, json=[])
    )

    with create_provider(make_config(base_url=web)) as provider:
        assert isinstance(provider, GitHubProvider)
        assert provider.base_url == "https://api.github.com"

    assert api.called


@respx.mock
def test_a_named_forge_is_taken_at_its_word() -> None:
    # No routes are mocked: a request of any kind would fail the test.
    with create_provider(make_config(provider="forgejo")) as provider:
        assert isinstance(provider, ForgejoProvider)


@respx.mock
def test_an_unknown_forge_name_lists_the_known_ones() -> None:
    with pytest.raises(ValueError, match="Unknown forge") as caught:
        create_provider(make_config(provider="bitbucket"))

    assert "gitlab, github, forgejo" in str(caught.value)


@respx.mock
def test_owner_is_refused_for_a_forge_that_has_no_owners() -> None:
    with pytest.raises(ValueError, match="--owner"):
        create_provider(make_config(provider="gitlab", owner="acme"))


@respx.mock
def test_owner_is_kept_for_github() -> None:
    with create_provider(make_config(provider="github", owner="acme")) as provider:
        assert isinstance(provider, GitHubProvider)


@respx.mock
def test_owner_is_refused_after_the_forge_turned_out_not_to_be_github() -> None:
    mock_probes(
        gitlab=not_found(), github=not_found(), forgejo=httpx.Response(200, json=[])
    )

    with pytest.raises(ValueError, match="--owner") as caught:
        create_provider(make_config(owner="acme"))

    assert "forgejo" in str(caught.value)
