import logging
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import final

import httpx
import pytest

import forge_mirror.mirror as mirror_mod
from forge_mirror.config import Config
from forge_mirror.mirror import (
    ENV_GIT_PASSWORD,
    SyncResult,
    dry_run,
    find_stale_mirrors,
    git_command,
    iter_local_mirrors,
    list_repos,
    mirror_repo,
    remove_mirror,
    repo_path,
    sync_all,
)
from forge_mirror.providers.base import Credentials, Repo


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


@pytest.fixture
def git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the user's own git configuration out of the git calls of a test."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return config


def _git(*args: str) -> str:
    """Run git for setting up or inspecting a test repository."""
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
    _ = _git("-C", str(repo), *identity, "commit", "-q", "--allow-empty", "-m", message)
    return _git("-C", str(repo), "rev-parse", "HEAD")


def _source_repo(tmp_path: Path) -> Path:
    """A local repository with one commit to mirror from."""
    source = tmp_path / "source"
    _ = _git("init", "-q", str(source))
    _ = _commit(source, "first")
    return source


def test_git_command_hands_the_token_to_git_only(git_config: Path) -> None:
    # A helper in the user's configuration, as a keychain would be: it must
    # neither be asked for the token nor be given it to store.
    trap = git_config.parent / "trap"
    git_config.write_text(f"[credential]\n\thelper = !echo >>{trap}\n")
    auth = Credentials("user", "secret")

    command, env = git_command(["credential", "fill"], auth)
    filled = subprocess.run(
        command,
        input="protocol=https\nhost=example.com\n\n",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    command, env = git_command(["credential", "approve"], auth)
    _ = subprocess.run(command, input=filled.stdout, env=env, check=True, text=True)

    assert "username=user\npassword=secret\n" in filled.stdout
    assert not any("secret" in arg for arg in command)
    assert not trap.exists()


def test_git_command_without_auth_has_no_helper() -> None:
    command, env = git_command(["fetch"], None)

    assert command[-1] == "fetch"
    assert not any(arg.startswith("credential.") for arg in command)
    assert ENV_GIT_PASSWORD not in env


def test_git_command_sets_a_low_speed_limit(git_config: Path) -> None:
    command, env = git_command(["config", "--get-regexp", r"^http\.lowspeed"], None)
    result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)

    settings = dict(line.split() for line in result.stdout.splitlines())
    assert int(settings["http.lowspeedlimit"]) > 0
    assert int(settings["http.lowspeedtime"]) > 0


def test_mirror_repo_clones_then_updates(tmp_path: Path, git_config: Path) -> None:
    source = _source_repo(tmp_path)
    target = tmp_path / "mirrors"
    repo = make_repo("g/source")

    assert mirror_repo(repo, str(source), target, None)
    head = _commit(source, "second")
    assert mirror_repo(repo, str(source), target, None)

    assert _git("--git-dir", str(repo_path(target, repo)), "rev-parse", "HEAD") == head


def test_mirror_repo_removes_a_token_from_the_remote_url(
    tmp_path: Path, git_config: Path
) -> None:
    source = _source_repo(tmp_path)
    target = tmp_path / "mirrors"
    repo = make_repo("g/source")
    assert mirror_repo(repo, str(source), target, None)
    mirror = repo_path(target, repo)
    old_url = "https://oauth2:secret@example.com/g/source.git"
    _ = _git("--git-dir", str(mirror), "remote", "set-url", "origin", old_url)

    assert mirror_repo(repo, str(source), target, None)

    assert _git("--git-dir", str(mirror), "remote", "get-url", "origin") == str(source)
    assert "secret" not in (mirror / "config").read_text()


@final
class _FakeProvider:
    def __init__(self, repos: list[Repo]) -> None:
        self._repos: list[Repo] = repos

    def iter_repos(self) -> Iterator[Repo]:
        yield from self._repos

    def credentials(self) -> Credentials:
        return Credentials("user", "secret")


@final
class _BrokenProvider:
    """A forge that hands out one page and then loses the connection."""

    def iter_repos(self) -> Iterator[Repo]:
        yield make_repo("g/a")
        raise httpx.ReadTimeout("page 2 timed out")

    def credentials(self) -> Credentials:
        return Credentials("user", "secret")


def _record(seen: list[str]):
    def recorder(
        repo: Repo,
        url: str,
        target_dir: Path,
        auth: Credentials | None,
    ) -> bool:
        seen.append(repo.full_name)
        return True

    return recorder


def test_sync_all_passes_the_token_only_for_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Credentials | None]] = []

    def recorder(
        repo: Repo,
        url: str,
        target_dir: Path,
        auth: Credentials | None,
    ) -> bool:
        calls.append((url, auth))
        return True

    monkeypatch.setattr(mirror_mod, "mirror_repo", recorder)
    provider = _FakeProvider([make_repo("g/a")])

    _ = sync_all(provider, make_config())
    _ = sync_all(provider, make_config(use_ssh=True))

    assert calls == [
        ("https://example/g/a.git", Credentials("user", "secret")),
        ("git@example:g/a.git", None),
    ]


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


def test_dry_run_without_prune_names_the_option(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mirror_mod, "remove_mirror", _explode)
    _ = make_mirror(tmp_path, "g/gone")
    provider = _FakeProvider([make_repo("g/new")])

    with caplog.at_level(logging.INFO):
        dry_run(provider, make_config(target_dir=tmp_path))

    assert "with --prune they would be deleted" in caplog.text


def test_dry_run_reports_a_cancelled_prune(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(mirror_mod, "remove_mirror", _explode)
    for name in ("g/one", "g/two", "g/three"):
        _ = make_mirror(tmp_path, name)
    provider = _FakeProvider([make_repo("g/still-there")])

    with caplog.at_level(logging.INFO):
        dry_run(provider, make_config(target_dir=tmp_path, prune=True, prune_limit=2))

    assert "would delete nothing" in caplog.text
    assert "--prune-limit=2" in caplog.text


def test_dry_run_leaves_archived_out_by_default(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    provider = _FakeProvider([make_repo("g/active"), make_repo("g/old", archived=True)])

    with caplog.at_level(logging.INFO):
        dry_run(provider, make_config(target_dir=tmp_path))

    assert "1 repositories: 1 to clone, 0 to update" in caplog.text
    assert "Archived repositories skipped: 1" in caplog.text
