import httpx
import pytest
import respx

from forge_mirror.providers.base import Credentials, Repo, describe_http_error
from forge_mirror.providers.forgejo import ForgejoProvider
from forge_mirror.providers.github import GitHubProvider
from forge_mirror.providers.gitlab import GitLabProvider

GITLAB_URL = "https://gl.example"
GITHUB_URL = "https://api.github.com"
FORGEJO_URL = "https://fj.example"


def test_gitlab_credentials_use_oauth2() -> None:
    provider = GitLabProvider(GITLAB_URL, "secret", 10.0)
    assert provider.credentials() == Credentials("oauth2", "secret")


def test_github_credentials_use_x_access_token() -> None:
    provider = GitHubProvider(GITHUB_URL, "secret", 10.0)
    assert provider.credentials() == Credentials("x-access-token", "secret")


@respx.mock
def test_gitlab_iter_repos_filters_by_membership() -> None:
    route = respx.get(
        f"{GITLAB_URL}/api/v4/projects", params={"membership": "true"}
    ).mock(return_value=httpx.Response(200, json=[_gitlab_item("grp/proj")]))
    with GitLabProvider(GITLAB_URL, "t", 10.0) as provider:
        list(provider.iter_repos())

    assert route.called


@respx.mock
def test_gitlab_iter_repos_maps_fields() -> None:
    respx.get(f"{GITLAB_URL}/api/v4/projects").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "path_with_namespace": "grp/proj",
                    "ssh_url_to_repo": "git@gl:grp/proj.git",
                    "http_url_to_repo": "https://gl/grp/proj.git",
                    "archived": True,
                }
            ],
        )
    )
    with GitLabProvider(GITLAB_URL, "t", 10.0) as provider:
        repos = list(provider.iter_repos())

    assert repos == [
        Repo("grp/proj", "git@gl:grp/proj.git", "https://gl/grp/proj.git", True)
    ]


@respx.mock
def test_gitlab_follows_link_header_pagination() -> None:
    page2 = f"{GITLAB_URL}/api/v4/projects?page=2"
    # A single route returns page 1 (with a next link) then page 2 (no link),
    # so the loop terminates after the second request.
    respx.get(f"{GITLAB_URL}/api/v4/projects").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[_gitlab_item("grp/one")],
                headers={"Link": f'<{page2}>; rel="next"'},
            ),
            httpx.Response(200, json=[_gitlab_item("grp/two")]),
        ]
    )
    with GitLabProvider(GITLAB_URL, "t", 10.0) as provider:
        names = [r.full_name for r in provider.iter_repos()]

    assert names == ["grp/one", "grp/two"]


@respx.mock
def test_github_iter_repos_maps_fields_and_uses_user_repos() -> None:
    route = respx.get(f"{GITHUB_URL}/user/repos").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "full_name": "octocat/hello",
                    "ssh_url": "git@github.com:octocat/hello.git",
                    "clone_url": "https://github.com/octocat/hello.git",
                    "archived": False,
                }
            ],
        )
    )
    with GitHubProvider(GITHUB_URL, "t", 10.0) as provider:
        repos = list(provider.iter_repos())

    assert route.called
    assert repos == [
        Repo(
            "octocat/hello",
            "git@github.com:octocat/hello.git",
            "https://github.com/octocat/hello.git",
            False,
        )
    ]


@respx.mock
def test_github_owner_organization_uses_orgs_endpoint() -> None:
    respx.get(f"{GITHUB_URL}/users/acme").mock(
        return_value=httpx.Response(200, json={"type": "Organization"})
    )
    org_route = respx.get(f"{GITHUB_URL}/orgs/acme/repos").mock(
        return_value=httpx.Response(200, json=[_github_item("acme/svc")])
    )
    with GitHubProvider(GITHUB_URL, "t", 10.0, owner="acme") as provider:
        names = [r.full_name for r in provider.iter_repos()]

    assert org_route.called
    assert names == ["acme/svc"]


@respx.mock
def test_github_owner_user_uses_users_endpoint() -> None:
    respx.get(f"{GITHUB_URL}/users/alice").mock(
        return_value=httpx.Response(200, json={"type": "User"})
    )
    user_route = respx.get(f"{GITHUB_URL}/users/alice/repos").mock(
        return_value=httpx.Response(200, json=[_github_item("alice/dotfiles")])
    )
    with GitHubProvider(GITHUB_URL, "t", 10.0, owner="alice") as provider:
        names = [r.full_name for r in provider.iter_repos()]

    assert user_route.called
    assert names == ["alice/dotfiles"]


@pytest.mark.parametrize(
    "given",
    [
        "https://github.com",
        "https://github.com/",
        "https://www.github.com",
        "http://github.com",
    ],
)
def test_github_web_host_is_rewritten_to_the_api_host(given: str) -> None:
    assert GitHubProvider.normalize_url(given).endswith("api.github.com")


def test_github_enterprise_url_is_left_untouched() -> None:
    given = "https://ghe.example/api/v3"
    assert GitHubProvider.normalize_url(given) == given


def test_other_forges_talk_to_the_url_as_given() -> None:
    given = "https://gl.example"
    assert GitLabProvider.normalize_url(given) == given
    assert ForgejoProvider.normalize_url(given) == given


def test_forgejo_credentials_use_token() -> None:
    provider = ForgejoProvider(FORGEJO_URL, "secret", 10.0)
    assert provider.credentials() == Credentials("token", "secret")


@respx.mock
def test_forgejo_iter_repos_maps_fields_and_authenticates() -> None:
    route = respx.get(f"{FORGEJO_URL}/api/v1/user/repos").mock(
        return_value=httpx.Response(
            200, json=[_forgejo_item("team/svc"), _forgejo_item("me/old", archived=True)]
        )
    )
    with ForgejoProvider(FORGEJO_URL, "t", 10.0) as provider:
        repos = list(provider.iter_repos())

    assert route.called
    # Forgejo insists on the word "token", a Bearer prefix is not the same thing.
    assert route.calls.last.request.headers["Authorization"] == "token t"
    assert repos == [
        Repo("team/svc", "git@fj:team/svc.git", "https://fj/team/svc.git", False),
        Repo("me/old", "git@fj:me/old.git", "https://fj/me/old.git", True),
    ]


@respx.mock
def test_forgejo_follows_link_header_pagination() -> None:
    page2 = f"{FORGEJO_URL}/api/v1/user/repos?limit=50&page=2"
    respx.get(f"{FORGEJO_URL}/api/v1/user/repos").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[_forgejo_item("me/one")],
                headers={"Link": f'<{page2}>; rel="next"'},
            ),
            httpx.Response(200, json=[_forgejo_item("me/two")]),
        ]
    )
    with ForgejoProvider(FORGEJO_URL, "t", 10.0) as provider:
        names = [r.full_name for r in provider.iter_repos()]

    assert names == ["me/one", "me/two"]


@respx.mock
def test_raises_on_http_error() -> None:
    respx.get(f"{GITLAB_URL}/api/v4/projects").mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"})
    )
    with (
        GitLabProvider(GITLAB_URL, "bad", 10.0) as provider,
        pytest.raises(httpx.HTTPStatusError),
    ):
        list(provider.iter_repos())


def _status_error(status: int, **response_args: object) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"{FORGEJO_URL}/api/v1/user/repos?limit=50")
    response = httpx.Response(status, request=request, **response_args)  # pyright: ignore[reportArgumentType]
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()
    return caught.value


def test_describe_http_error_quotes_the_forge() -> None:
    exc = _status_error(
        403,
        json={
            "message": "token does not have at least one of required scope(s): "
            "[read:repository]"
        },
    )

    described = describe_http_error(exc)

    assert described == (
        "403 for GET https://fj.example/api/v1/user/repos: token does not have "
        "at least one of required scope(s): [read:repository]"
    )


def test_describe_http_error_passes_through_a_proxy_page() -> None:
    exc = _status_error(403, html="<html>\n  <body>Access denied</body>\n</html>")

    assert describe_http_error(exc).endswith(
        ": <html> <body>Access denied</body> </html>"
    )


def test_describe_http_error_without_a_body_still_names_the_request() -> None:
    exc = _status_error(500)

    assert describe_http_error(exc) == (
        "500 for GET https://fj.example/api/v1/user/repos"
    )


def _gitlab_item(path: str) -> dict[str, object]:
    return {
        "path_with_namespace": path,
        "ssh_url_to_repo": f"git@gl:{path}.git",
        "http_url_to_repo": f"https://gl/{path}.git",
        "archived": False,
    }


def _github_item(full_name: str) -> dict[str, object]:
    return {
        "full_name": full_name,
        "ssh_url": f"git@github.com:{full_name}.git",
        "clone_url": f"https://github.com/{full_name}.git",
        "archived": False,
    }


def _forgejo_item(full_name: str, archived: bool = False) -> dict[str, object]:
    return {
        "full_name": full_name,
        "ssh_url": f"git@fj:{full_name}.git",
        "clone_url": f"https://fj/{full_name}.git",
        "archived": archived,
    }
