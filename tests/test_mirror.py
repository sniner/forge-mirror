from collections.abc import Iterator
from pathlib import Path
from typing import final

import pytest

import gitlab_mirror.mirror as mirror_mod
from gitlab_mirror.config import Config
from gitlab_mirror.gitlab import Project
from gitlab_mirror.mirror import clone_url, mask_token, repo_path, sync_all


def make_project(path: str = "group/repo", archived: bool = False) -> Project:
    return Project(
        path_with_namespace=path,
        ssh_url_to_repo=f"git@gl.example:{path}.git",
        http_url_to_repo=f"https://gl.example/{path}.git",
        archived=archived,
    )


def make_config(
    *,
    use_ssh: bool = False,
    include_archived: bool = False,
    jobs: int = 2,
) -> Config:
    return Config(
        gitlab_url="https://gl.example",
        token="secret",
        target_dir=Path("/backup"),
        use_ssh=use_ssh,
        include_archived=include_archived,
        jobs=jobs,
        timeout=30.0,
    )


def test_repo_path() -> None:
    assert repo_path(Path("/backup"), make_project()) == Path("/backup/group/repo.git")


def test_clone_url_https_injects_token() -> None:
    url = clone_url(make_project(), use_ssh=False, token="secret")
    assert url == "https://oauth2:secret@gl.example/group/repo.git"


def test_clone_url_ssh_unchanged() -> None:
    url = clone_url(make_project(), use_ssh=True, token="secret")
    assert url == "git@gl.example:group/repo.git"


def test_mask_token_hides_credentials() -> None:
    masked = mask_token("https://oauth2:secret@gl.example/group/repo.git")
    assert "secret" not in masked
    assert masked == "https://***@gl.example/group/repo.git"


def test_mask_token_passes_through_plain_url() -> None:
    assert mask_token("https://gl.example/x.git") == "https://gl.example/x.git"


@final
class _FakeClient:
    def __init__(self, projects: list[Project]) -> None:
        self._projects: list[Project] = projects

    def iter_projects(self) -> Iterator[Project]:
        yield from self._projects


def _record(seen: list[str]):
    def recorder(project: Project, _config: Config) -> bool:
        seen.append(project.path_with_namespace)
        return True

    return recorder


def test_sync_all_skips_archived_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(mirror_mod, "mirror_project", _record(seen))

    client = _FakeClient([make_project("g/active"), make_project("g/old", archived=True)])
    result = sync_all(client, make_config())

    assert seen == ["g/active"]
    assert result.succeeded == 1
    assert result.failed == 0


def test_sync_all_includes_archived_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(mirror_mod, "mirror_project", _record(seen))

    client = _FakeClient([make_project("g/active"), make_project("g/old", archived=True)])
    _ = sync_all(client, make_config(include_archived=True))

    assert set(seen) == {"g/active", "g/old"}
