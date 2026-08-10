import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import final

import httpx
import pytest

import forge_mirror.mirror as mirror_mod
from forge_mirror.config import Config
from forge_mirror.mirror import (
    SyncResult,
    dry_run,
    find_stale_mirrors,
    iter_local_mirrors,
    list_repos,
    mask_token,
    remove_mirror,
    repo_path,
    sync_all,
)
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
    target_dir: Path = Path("/backup"),
    owner: str | None = None,
    use_ssh: bool = False,
    include_archived: bool = False,
    prune: bool = False,
    prune_limit: int = 10,
    jobs: int = 2,
) -> Config:
    return Config(
        provider="gitlab",
        base_url="https://example",
        token="secret",
        target_dir=target_dir,
        owner=owner,
        list_only=False,
        dry_run=False,
        use_ssh=use_ssh,
        include_archived=include_archived,
        prune=prune,
        prune_limit=prune_limit,
        jobs=jobs,
        timeout=30.0,
    )


def make_mirror(target_dir: Path, full_name: str) -> Path:
    """Create a directory that passes for a bare mirror of full_name."""
    path = target_dir / f"{full_name}.git"
    (path / "objects").mkdir(parents=True)
    (path / "HEAD").write_text("ref: refs/heads/main\n")
    return path


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


@final
class _BrokenProvider:
    """A forge that hands out one page and then loses the connection."""

    def iter_repos(self) -> Iterator[Repo]:
        yield make_repo("g/a")
        raise httpx.ReadTimeout("page 2 timed out")

    def clone_url(self, repo: Repo, *, use_ssh: bool) -> str:
        return repo.https_url


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


def test_iter_local_mirrors_finds_nested_namespaces(tmp_path: Path) -> None:
    expected = {
        make_mirror(tmp_path, "group/repo"),
        make_mirror(tmp_path, "group/sub/deep"),
        make_mirror(tmp_path, "toplevel"),
    }
    assert set(iter_local_mirrors(tmp_path)) == expected


def test_iter_local_mirrors_does_not_descend_into_a_mirror(tmp_path: Path) -> None:
    mirror = make_mirror(tmp_path, "group/repo")
    (mirror / "modules" / "nested.git").mkdir(parents=True)

    assert list(iter_local_mirrors(tmp_path)) == [mirror]


def test_iter_local_mirrors_ignores_working_copies_and_dot_dirs(tmp_path: Path) -> None:
    (tmp_path / "checkout" / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".snapshots" / "group" / "repo.git" / "objects").mkdir(parents=True)
    mirror = make_mirror(tmp_path, "group/repo")

    assert list(iter_local_mirrors(tmp_path)) == [mirror]


def test_iter_local_mirrors_ignores_symlinks(tmp_path: Path) -> None:
    mirror = make_mirror(tmp_path, "group/repo")
    (tmp_path / "link.git").symlink_to(mirror, target_is_directory=True)

    assert list(iter_local_mirrors(tmp_path)) == [mirror]


def test_iter_local_mirrors_on_missing_directory(tmp_path: Path) -> None:
    assert list(iter_local_mirrors(tmp_path / "nope")) == []


def test_find_stale_mirrors_reports_the_old_location(tmp_path: Path) -> None:
    _ = make_mirror(tmp_path, "new-group/repo")
    old = make_mirror(tmp_path, "old-group/repo")

    stale = find_stale_mirrors(tmp_path, [make_repo("new-group/repo")])

    assert stale == [old]


def test_find_stale_mirrors_keeps_archived_repositories(tmp_path: Path) -> None:
    _ = make_mirror(tmp_path, "g/old")

    stale = find_stale_mirrors(tmp_path, [make_repo("g/old", archived=True)])

    assert stale == []


def test_find_stale_mirrors_honours_the_scope(tmp_path: Path) -> None:
    gone = make_mirror(tmp_path, "my-org/gone")
    _ = make_mirror(tmp_path, "other-org/untouched")

    stale = find_stale_mirrors(tmp_path, [make_repo("my-org/kept")], scope="my-org")

    assert stale == [gone]


def test_remove_mirror_deletes_the_emptied_namespace(tmp_path: Path) -> None:
    mirror = make_mirror(tmp_path, "group/sub/repo")

    assert remove_mirror(mirror, tmp_path) is True
    assert not (tmp_path / "group").exists()
    assert tmp_path.exists()


def test_remove_mirror_keeps_a_namespace_still_in_use(tmp_path: Path) -> None:
    mirror = make_mirror(tmp_path, "group/repo")
    sibling = make_mirror(tmp_path, "group/other")

    assert remove_mirror(mirror, tmp_path) is True
    assert sibling.exists()


def test_remove_mirror_refuses_anything_but_a_bare_repo(tmp_path: Path) -> None:
    stray = tmp_path / "notes.git"
    stray.mkdir()

    assert remove_mirror(stray, tmp_path) is False
    assert stray.exists()


def _sync_with_mirrors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    local: list[str],
    remote: list[str],
    prune: bool = False,
    prune_limit: int = 10,
) -> SyncResult:
    """Run sync_all over prepared local mirrors, without touching git."""
    monkeypatch.setattr(mirror_mod, "mirror_repo", _record([]))
    for full_name in local:
        _ = make_mirror(tmp_path, full_name)
    provider = _FakeProvider([make_repo(name) for name in remote])
    config = make_config(target_dir=tmp_path, prune=prune, prune_limit=prune_limit)
    return sync_all(provider, config)


def test_sync_all_reports_stale_mirrors_without_prune(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _sync_with_mirrors(
        monkeypatch, tmp_path, local=["g/gone", "g/kept"], remote=["g/kept"]
    )

    assert result.stale == 1
    assert result.removed == 0
    assert result.unremoved == 0
    assert (tmp_path / "g/gone.git").exists()


def test_sync_all_removes_stale_mirrors_with_prune(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _sync_with_mirrors(
        monkeypatch,
        tmp_path,
        local=["old/repo", "new/repo"],
        remote=["new/repo"],
        prune=True,
    )

    assert result.stale == 1
    assert result.removed == 1
    assert not (tmp_path / "old").exists()
    assert (tmp_path / "new/repo.git").exists()


def test_sync_all_stops_at_the_prune_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _sync_with_mirrors(
        monkeypatch,
        tmp_path,
        local=["g/a", "g/b", "g/c"],
        remote=["g/a"],
        prune=True,
        prune_limit=1,
    )

    assert result.stale == 2
    assert result.removed == 0
    assert result.unremoved == 2
    assert (tmp_path / "g/b.git").exists()
    assert (tmp_path / "g/c.git").exists()


def test_sync_all_prune_limit_zero_removes_everything_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _sync_with_mirrors(
        monkeypatch,
        tmp_path,
        local=["g/a", "g/b", "g/c"],
        remote=["g/a"],
        prune=True,
        prune_limit=0,
    )

    assert result.removed == 2
    assert (tmp_path / "g/a.git").exists()


def test_sync_all_keeps_everything_when_the_listing_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _sync_with_mirrors(
        monkeypatch, tmp_path, local=["g/a", "g/b"], remote=[], prune=True
    )

    assert result.stale == 0
    assert result.removed == 0
    assert (tmp_path / "g/a.git").exists()


def test_sync_all_counts_a_mirror_it_could_not_remove(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mirror_mod, "mirror_repo", _record([]))
    (tmp_path / "g" / "junk.git").mkdir(parents=True)
    provider = _FakeProvider([make_repo("g/kept")])

    result = sync_all(provider, make_config(target_dir=tmp_path, prune=True))

    assert result.stale == 1
    assert result.removed == 0
    assert result.unremoved == 1
    assert (tmp_path / "g" / "junk.git").exists()


def test_sync_all_keeps_everything_when_the_listing_breaks_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mirror_mod, "mirror_repo", _record([]))
    _ = make_mirror(tmp_path, "g/a")
    _ = make_mirror(tmp_path, "g/b")

    with pytest.raises(httpx.ReadTimeout):
        _ = sync_all(_BrokenProvider(), make_config(target_dir=tmp_path, prune=True))

    assert (tmp_path / "g/a.git").exists()
    assert (tmp_path / "g/b.git").exists()


def test_sync_all_keeps_archived_repositories_when_pruning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mirror_mod, "mirror_repo", _record([]))
    _ = make_mirror(tmp_path, "g/archived")
    provider = _FakeProvider([make_repo("g/archived", archived=True)])

    result = sync_all(provider, make_config(target_dir=tmp_path, prune=True))

    assert result.stale == 0
    assert (tmp_path / "g/archived.git").exists()


def test_list_repos_writes_plain_names_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = _FakeProvider([make_repo("g/one"), make_repo("g/two")])

    count = list_repos(provider, make_config())

    assert count == 2
    # Nothing but the names, so the list survives a pipe.
    assert capsys.readouterr().out == "g/one\ng/two\n"


def test_list_repos_leaves_archived_out_by_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = _FakeProvider([make_repo("g/active"), make_repo("g/old", archived=True)])

    count = list_repos(provider, make_config())

    assert count == 1
    assert capsys.readouterr().out == "g/active\n"


def test_list_repos_takes_archived_along_when_asked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = _FakeProvider([make_repo("g/active"), make_repo("g/old", archived=True)])

    count = list_repos(provider, make_config(include_archived=True))

    assert count == 2
    assert capsys.readouterr().out == "g/active\ng/old\n"


def test_list_repos_needs_no_target_directory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = _FakeProvider([make_repo("g/one")])
    config = replace(make_config(), target_dir=None, list_only=True)

    assert list_repos(provider, config) == 1
    assert capsys.readouterr().out == "g/one\n"


def _explode(*args: object, **kwargs: object) -> bool:
    raise AssertionError("a dry run must not touch anything")


def test_dry_run_neither_mirrors_nor_deletes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mirror_mod, "mirror_repo", _explode)
    monkeypatch.setattr(mirror_mod, "remove_mirror", _explode)
    kept = make_mirror(tmp_path, "g/kept")
    stale = make_mirror(tmp_path, "g/gone")
    provider = _FakeProvider([make_repo("g/kept"), make_repo("g/new")])

    with caplog.at_level(logging.INFO):
        dry_run(provider, make_config(target_dir=tmp_path, prune=True))

    assert kept.exists()
    assert stale.exists()
    assert "2 repositories: 1 to clone, 1 to update" in caplog.text
    assert "Would clone g/new" in caplog.text
    assert "--prune would delete 1 mirror(s)" in caplog.text
    assert str(stale) in caplog.text


def test_dry_run_without_prune_says_how_to_carry_it_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mirror_mod, "remove_mirror", _explode)
    _ = make_mirror(tmp_path, "g/gone")
    provider = _FakeProvider([make_repo("g/new")])

    with caplog.at_level(logging.INFO):
        dry_run(provider, make_config(target_dir=tmp_path))

    assert "add --prune" in caplog.text
    assert "drop --dry-run" in caplog.text


def test_dry_run_reports_a_cancelled_prune(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mirror_mod, "remove_mirror", _explode)
    for name in ("g/one", "g/two", "g/three"):
        _ = make_mirror(tmp_path, name)
    provider = _FakeProvider([make_repo("g/still-there")])

    with caplog.at_level(logging.INFO):
        dry_run(provider, make_config(target_dir=tmp_path, prune=True, prune_limit=2))

    assert "would delete nothing here" in caplog.text
    assert "--prune-limit=2" in caplog.text


def test_dry_run_leaves_archived_out_by_default(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    provider = _FakeProvider([make_repo("g/active"), make_repo("g/old", archived=True)])

    with caplog.at_level(logging.INFO):
        dry_run(provider, make_config(target_dir=tmp_path))

    assert "1 repositories: 1 to clone, 0 to update" in caplog.text
    assert "1 archived one(s) left out" in caplog.text
