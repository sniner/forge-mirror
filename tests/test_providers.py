import httpx
import pytest
import respx

from forge_mirror.providers.base import Repo
from forge_mirror.providers.github import GitHubProvider
from forge_mirror.providers.gitlab import GitLabProvider

GITLAB_URL = "https://gl.example"
GITHUB_URL = "https://api.github.com"


def make_repo() -> Repo:
    return Repo(
        full_name="group/repo",
        ssh_url="git@gl.example:group/repo.git",
        https_url="https://gl.example/group/repo.git",
        archived=False,
    )


def test_gitlab_clone_url_embeds_oauth2_token() -> None:
    provider = GitLabProvider(GITLAB_URL, "secret", 10.0)
    url = provider.clone_url(make_repo(), use_ssh=False)
    assert url == "https://oauth2:secret@gl.example/group/repo.git"


def test_github_clone_url_embeds_x_access_token() -> None:
    provider = GitHubProvider(GITHUB_URL, "secret", 10.0)
    url = provider.clone_url(make_repo(), use_ssh=False)
    assert url == "https://x-access-token:secret@gl.example/group/repo.git"


def test_clone_url_ssh_is_unchanged() -> None:
    provider = GitLabProvider(GITLAB_URL, "secret", 10.0)
    assert (
        provider.clone_url(make_repo(), use_ssh=True) == "git@gl.example:group/repo.git"
    )


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


@respx.mock
def test_raises_on_http_error() -> None:
    respx.get(f"{GITLAB_URL}/api/v4/projects").mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"})
    )
    with GitLabProvider(GITLAB_URL, "bad", 10.0) as provider:
        with pytest.raises(httpx.HTTPStatusError):
            list(provider.iter_repos())


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
