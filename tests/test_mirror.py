from collections.abc import Iterator
from pathlib import Path
from typing import final

import pytest

import forge_mirror.mirror as mirror_mod
from forge_mirror.config import Config
from forge_mirror.mirror import mask_token, repo_path, sync_all
from forge_mirror.providers.base import Repo


def make_repo(full_name: str = "group/repo", archived: bool = False) -> Repo:
    return Repo(
        full_name=full_name,
        ssh_url=f"git@example:{full_name}.git",
        https_url=f"https://example/{full_name}.git",
        archived=archived,
    )


def make_config(
    *,
    use_ssh: bool = False,
    include_archived: bool = False,
    jobs: int = 2,
) -> Config:
    return Config(
        provider="gitlab",
        base_url="https://example",
        token="secret",
        target_dir=Path("/backup"),
        owner=None,
        use_ssh=use_ssh,
        include_archived=include_archived,
        jobs=jobs,
        timeout=30.0,
    )


def test_repo_path() -> None:
    assert repo_path(Path("/backup"), make_repo()) == Path("/backup/group/repo.git")


def test_mask_token_hides_credentials() -> None:
    masked = mask_token("https://oauth2:secret@example/group/repo.git")
    assert "secret" not in masked
    assert masked == "https://***@example/group/repo.git"


def test_mask_token_passes_through_plain_url() -> None:
    assert mask_token("https://example/x.git") == "https://example/x.git"


@final
class _FakeProvider:
    def __init__(self, repos: list[Repo]) -> None:
        self._repos: list[Repo] = repos

    def iter_repos(self) -> Iterator[Repo]:
        yield from self._repos

    def clone_url(self, repo: Repo, *, use_ssh: bool) -> str:
        return repo.ssh_url if use_ssh else repo.https_url


def _record(seen: list[str]):
    def recorder(repo: Repo, clone_url: str, target_dir: Path) -> bool:
        seen.append(repo.full_name)
        return True

    return recorder


def test_sync_all_skips_archived_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(mirror_mod, "mirror_repo", _record(seen))

    provider = _FakeProvider([make_repo("g/active"), make_repo("g/old", archived=True)])
    result = sync_all(provider, make_config())

    assert seen == ["g/active"]
    assert result.succeeded == 1
    assert result.failed == 0


def test_sync_all_includes_archived_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(mirror_mod, "mirror_repo", _record(seen))

    provider = _FakeProvider([make_repo("g/active"), make_repo("g/old", archived=True)])
    _ = sync_all(provider, make_config(include_archived=True))

    assert set(seen) == {"g/active", "g/old"}
