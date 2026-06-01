"""Clone repositories as bare mirrors and update them."""

import logging
import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from forge_mirror.config import Config
from forge_mirror.providers.base import Repo

logger = logging.getLogger(__name__)


class RepoSource(Protocol):
    """The subset of a provider that sync_all needs (implemented by Provider)."""

    def iter_repos(self) -> Iterator[Repo]: ...

    def clone_url(self, repo: Repo, *, use_ssh: bool) -> str: ...


def repo_path(target_dir: Path, repo: Repo) -> Path:
    """Local path of the bare repository for a repo."""
    return target_dir / f"{repo.full_name}.git"


def mask_token(url: str) -> str:
    """Replace embedded credentials in a URL with *** for logging."""
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    _, _, host_part = rest.partition("@")
    return f"{scheme}://***@{host_part}"


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True)


def mirror_repo(repo: Repo, clone_url: str, target_dir: Path) -> bool:
    """Clone the repo as a mirror or update an existing one.

    Returns True on success, False on a git error.
    """
    path = repo_path(target_dir, repo)

    try:
        if path.exists():
            logger.info("Updating %s", repo.full_name)
            _run_git(["git", "--git-dir", str(path), "remote", "update", "--prune"])
        else:
            logger.info("Cloning %s", repo.full_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["git", "clone", "--mirror", clone_url, str(path)])
    except subprocess.CalledProcessError as exc:
        logger.error(
            "git error for %s (%s): %s",
            repo.full_name,
            mask_token(clone_url),
            (exc.stderr or "").strip(),
        )
        return False
    return True


@dataclass
class SyncResult:
    """Result of a complete mirror run."""

    succeeded: int
    failed: int


def sync_all(provider: RepoSource, config: Config) -> SyncResult:
    """Mirror all (non-archived) repositories in parallel."""
    repos = [
        r for r in provider.iter_repos() if config.include_archived or not r.archived
    ]
    logger.info("Mirroring %d repositories (jobs=%d)", len(repos), config.jobs)

    def work(repo: Repo) -> bool:
        clone_url = provider.clone_url(repo, use_ssh=config.use_ssh)
        return mirror_repo(repo, clone_url, config.target_dir)

    with ThreadPoolExecutor(max_workers=config.jobs) as executor:
        results = list(executor.map(work, repos))

    succeeded = sum(results)
    failed = len(results) - succeeded
    logger.info("Done: %d succeeded, %d failed", succeeded, failed)
    return SyncResult(succeeded=succeeded, failed=failed)
