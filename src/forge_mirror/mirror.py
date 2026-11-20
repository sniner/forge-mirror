"""Clone repositories as bare mirrors, update them and drop stale ones."""

import logging
import os
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from forge_mirror.config import Config
from forge_mirror.providers.base import Credentials, Repo

logger = logging.getLogger(__name__)


class RepoSource(Protocol):
    """The subset of a provider that sync_all needs (implemented by Provider)."""

    def iter_repos(self) -> Iterator[Repo]: ...

    def credentials(self) -> Credentials: ...


def repo_path(target_dir: Path, repo: Repo) -> Path:
    """Local path of the bare repository for a repo."""
    return target_dir / f"{repo.full_name}.git"


ENV_GIT_USERNAME = "FORGE_MIRROR_GIT_USERNAME"
ENV_GIT_PASSWORD = "FORGE_MIRROR_GIT_PASSWORD"

# Reads the credentials from the environment of the git process, so the token
# is neither written to the mirror's config nor visible on a command line. git
# asks a helper only after the server has answered 401, so public repositories
# are still fetched without the token.
_CREDENTIAL_HELPER = (
    '!f() { if [ "$1" = get ]; then '
    "printf 'username=%s\\npassword=%s\\n' "
    f'"${ENV_GIT_USERNAME}" "${ENV_GIT_PASSWORD}"; fi; }}; f'
)

# The empty value clears the helpers from the user's git configuration. git
# hands credentials that worked to every helper to store, so a keychain helper
# would otherwise keep a copy of the token.
_CREDENTIAL_OPTIONS = [
    "-c",
    "credential.helper=",
    "-c",
    f"credential.helper={_CREDENTIAL_HELPER}",
]


def git_command(
    args: list[str],
    auth: Credentials | None,
) -> tuple[list[str], dict[str, str]]:
    """The command line and environment for running git with args.

    Without auth (SSH) git authenticates with the user's key. A prompt is turned
    off either way: with several jobs in parallel it would wait for input that
    never comes.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if auth is None:
        return ["git", *args], env
    env[ENV_GIT_USERNAME] = auth.username
    env[ENV_GIT_PASSWORD] = auth.password
    return ["git", *_CREDENTIAL_OPTIONS, *args], env


def _run_git(args: list[str], auth: Credentials | None = None) -> None:
    command, env = git_command(args, auth)
    _ = subprocess.run(command, check=True, capture_output=True, text=True, env=env)


def mirror_repo(
    repo: Repo,
    url: str,
    target_dir: Path,
    auth: Credentials | None,
) -> bool:
    """Clone the repo as a mirror or update an existing one.

    auth is the token for HTTPS, None for SSH. Returns True on success, False on
    a git error.
    """
    path = repo_path(target_dir, repo)

    try:
        if path.exists():
            logger.info("Updating %s", repo.full_name)
            # A mirror cloned with the token in its URL keeps it there unless the
            # URL is replaced, and replacing it on every update also moves an
            # existing mirror to SSH or back when --ssh is added or dropped.
            _run_git(["--git-dir", str(path), "remote", "set-url", "origin", url])
            _run_git(["--git-dir", str(path), "remote", "update", "--prune"], auth)
        else:
            logger.info("Cloning %s", repo.full_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["clone", "--mirror", url, str(path)], auth)
    except subprocess.CalledProcessError as exc:
        logger.error(
            "git error for %s (%s): %s",
            repo.full_name,
            url,
            (exc.stderr or "").strip(),
        )
        return False
    return True


def iter_local_mirrors(root: Path) -> Iterator[Path]:
    """Yield every bare mirror below root.

    A mirror is a directory whose name ends in ".git"; it is never descended
    into, so paths inside a repository cannot be mistaken for mirrors. Symlinks
    are ignored because they may lead outside the mirror directory.
    """
    if not root.is_dir():
        return
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError as exc:
            logger.warning("Cannot inspect %s for stale mirrors: %s", current, exc)
            continue
        for entry in entries:
            if entry.is_symlink() or not entry.is_dir():
                continue
            if entry.name == ".git":
                # The repository of a working copy, not one of our mirrors.
                continue
            if entry.name.endswith(".git"):
                yield entry
            elif not entry.name.startswith("."):
                # Namespaces never start with a dot, so skipping those keeps
                # snapshot directories (.zfs, .snapshots) out of the way.
                pending.append(entry)


def find_stale_mirrors(
    target_dir: Path,
    repos: Iterable[Repo],
    *,
    scope: str | None = None,
) -> list[Path]:
    """Local mirrors that no longer have a repository in the remote listing.

    The keep set covers every listed repository, archived ones included, so
    that archiving a repository never turns its mirror into a candidate for
    deletion. With a scope only that subdirectory of target_dir is examined.
    """
    keep = {repo_path(target_dir, repo) for repo in repos}
    root = target_dir / scope if scope else target_dir
    return sorted(path for path in iter_local_mirrors(root) if path not in keep)


def _is_bare_repo(path: Path) -> bool:
    """Whether path looks like a bare git repository."""
    return (path / "HEAD").is_file() and (path / "objects").is_dir()


def _remove_empty_parents(start: Path, stop: Path) -> None:
    """Remove the namespace directories a deleted mirror left empty."""
    current = start
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def remove_mirror(path: Path, target_dir: Path) -> bool:
    """Delete a stale mirror and the namespace directories it empties.

    Returns True on success, False if the directory was kept.
    """
    if not _is_bare_repo(path):
        logger.error("Keeping %s: not a bare repository, delete it by hand", path)
        return False
    logger.info("Removing %s", path)
    try:
        shutil.rmtree(path)
    except OSError as exc:
        logger.error("Could not remove %s: %s", path, exc)
        return False
    _remove_empty_parents(path.parent, target_dir)
    return True


_NO_LISTING = (
    "Not looking for stale mirrors: the forge listed no repositories at all, "
    "which points at the token rather than at an empty forge"
)


def _log_paths(level: int, paths: Iterable[Path]) -> None:
    for path in paths:
        logger.log(level, "  %s", path)


def handle_stale_mirrors(repos: list[Repo], config: Config) -> tuple[int, int, int]:
    """Report the mirrors without a remote repository, and with --prune drop them.

    Returns (found, removed, errors).
    """
    if not repos:
        logger.warning("%s", _NO_LISTING)
        return 0, 0, 0

    target_dir = config.target_dir
    assert target_dir is not None, "pruning needs a target directory"

    stale = find_stale_mirrors(target_dir, repos, scope=config.owner)
    if not stale:
        return 0, 0, 0

    if not config.prune:
        logger.warning(
            "%d mirror(s) have no repository on the forge, pass --prune to delete them:",
            len(stale),
        )
        _log_paths(logging.WARNING, stale)
        return len(stale), 0, 0

    if config.prune_limit and len(stale) > config.prune_limit:
        logger.error(
            "Deleting nothing: %d mirrors would go, over --prune-limit=%d. Such a jump "
            "is usually a token that lost access, not repositories that are gone. "
            "Check this list, then raise --prune-limit (0 turns the check off):",
            len(stale),
            config.prune_limit,
        )
        _log_paths(logging.ERROR, stale)
        return len(stale), 0, len(stale)

    removed = sum(remove_mirror(path, target_dir) for path in stale)
    return len(stale), removed, len(stale) - removed


def list_repos(provider: RepoSource, config: Config) -> int:
    """Report what a mirror run would take, and return how many that is.

    The names go to standard output, one per line and nothing else, so the
    list can be counted or filtered by another command; what the run has to
    say about itself stays on the log, where it does not get in the way.
    """
    listed = list(provider.iter_repos())
    repos = [r for r in listed if config.include_archived or not r.archived]
    for repo in repos:
        # Not the logger: this list is the answer, not a remark about the run.
        print(repo.full_name)

    skipped = len(listed) - len(repos)
    if skipped:
        logger.info(
            "%d repositories would be mirrored, %d archived one(s) left out "
            "(--include-archived takes them along)",
            len(repos),
            skipped,
        )
    else:
        logger.info("%d repositories would be mirrored", len(repos))
    return len(repos)


def _report_stale_dry_run(listed: list[Repo], config: Config, target_dir: Path) -> None:
    """Say what the stale mirrors are and what --prune would make of them."""
    if not listed:
        logger.warning("%s", _NO_LISTING)
        return

    stale = find_stale_mirrors(target_dir, listed, scope=config.owner)
    if not stale:
        return

    if not config.prune:
        logger.warning(
            "%d mirror(s) have no repository on the forge; add --prune to see "
            "them as deletions, and drop --dry-run to carry them out:",
            len(stale),
        )
        _log_paths(logging.WARNING, stale)
    elif config.prune_limit and len(stale) > config.prune_limit:
        logger.error(
            "--prune would delete nothing here: %d mirrors are over "
            "--prune-limit=%d, which cancels the deletion completely. Such a "
            "jump is usually a token that lost access. Check this list, then "
            "raise the limit (0 turns the check off):",
            len(stale),
            config.prune_limit,
        )
        _log_paths(logging.ERROR, stale)
    else:
        logger.warning("--prune would delete %d mirror(s):", len(stale))
        _log_paths(logging.WARNING, stale)


def dry_run(provider: RepoSource, config: Config) -> None:
    """Report what a mirror run would do, and do none of it.

    The listing is read in full and the local mirrors are inspected, exactly as
    a real run would; nothing is cloned, updated or deleted.
    """
    target_dir = config.target_dir
    assert target_dir is not None, "a dry run needs a target directory"

    logger.info("Dry run: nothing is cloned, updated or deleted")

    listed = list(provider.iter_repos())
    repos = [r for r in listed if config.include_archived or not r.archived]
    plan = [(repo, repo_path(target_dir, repo).exists()) for repo in repos]
    updates = sum(1 for _, exists in plan if exists)

    logger.info(
        "%d repositories: %d to clone, %d to update%s",
        len(plan),
        len(plan) - updates,
        updates,
        " (-v names the updates too)" if updates else "",
    )
    skipped = len(listed) - len(repos)
    if skipped:
        logger.info(
            "%d archived one(s) left out (--include-archived takes them along)",
            skipped,
        )

    for repo, exists in plan:
        # The updates are the uninteresting majority of a settled mirror
        # directory; the clones are what this run would actually change.
        if exists:
            logger.debug("Would update %s", repo.full_name)
        else:
            logger.info("Would clone %s", repo.full_name)

    _report_stale_dry_run(listed, config, target_dir)
    logger.info("Dry run finished, nothing was touched")


@dataclass
class SyncResult:
    """Result of a complete mirror run.

    stale counts the mirrors without a repository on the forge, removed those
    of them that --prune deleted, and unremoved those it was asked to delete
    but could not -- a run is only clean when both failed and unremoved are 0.
    """

    succeeded: int
    failed: int
    stale: int = 0
    removed: int = 0
    unremoved: int = 0


def sync_all(provider: RepoSource, config: Config) -> SyncResult:
    """Mirror all (non-archived) repositories in parallel, then handle stale ones.

    The listing is read completely before anything else happens: a forge that
    fails halfway through pagination has to abort the run, because a partial
    list would make pruning read the missing repositories as deleted.
    """
    target_dir = config.target_dir
    assert target_dir is not None, "a mirror run needs a target directory"

    listed = list(provider.iter_repos())
    repos = [r for r in listed if config.include_archived or not r.archived]
    logger.info("Mirroring %d repositories (jobs=%d)", len(repos), config.jobs)

    auth = None if config.use_ssh else provider.credentials()

    def work(repo: Repo) -> bool:
        url = repo.ssh_url if config.use_ssh else repo.https_url
        return mirror_repo(repo, url, target_dir, auth)

    with ThreadPoolExecutor(max_workers=config.jobs) as executor:
        results = list(executor.map(work, repos))

    succeeded = sum(results)
    failed = len(results) - succeeded
    stale, removed, unremoved = handle_stale_mirrors(listed, config)

    logger.info("Done: %d succeeded, %d failed", succeeded, failed)
    if stale:
        logger.info(
            "Stale mirrors: %d (%d removed, %d kept)",
            stale,
            removed,
            stale - removed,
        )
    return SyncResult(
        succeeded=succeeded,
        failed=failed,
        stale=stale,
        removed=removed,
        unremoved=unremoved,
    )
