"""Clone repositories as bare mirrors and update them."""

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from gitlab_mirror.config import Config
from gitlab_mirror.gitlab import Project, ProjectSource

logger = logging.getLogger(__name__)


def repo_path(target_dir: Path, project: Project) -> Path:
    """Local path of the bare repository for a project."""
    return target_dir / f"{project.path_with_namespace}.git"


def clone_url(project: Project, *, use_ssh: bool, token: str) -> str:
    """Clone URL for the project; for HTTPS the token is embedded."""
    if use_ssh:
        return project.ssh_url_to_repo
    url = project.http_url_to_repo
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    return f"{scheme}://oauth2:{token}@{rest}"


def mask_token(url: str) -> str:
    """Replace embedded credentials in a URL with *** for logging."""
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    _, _, host_part = rest.partition("@")
    return f"{scheme}://***@{host_part}"


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True)


def mirror_project(project: Project, config: Config) -> bool:
    """Clone the project as a mirror or update an existing one.

    Returns True on success, False on a git error.
    """
    path = repo_path(config.target_dir, project)
    url = clone_url(project, use_ssh=config.use_ssh, token=config.token)

    try:
        if path.exists():
            logger.info("Updating %s", project.path_with_namespace)
            _run_git(["git", "--git-dir", str(path), "remote", "update", "--prune"])
        else:
            logger.info("Cloning %s", project.path_with_namespace)
            path.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["git", "clone", "--mirror", url, str(path)])
    except subprocess.CalledProcessError as exc:
        logger.error(
            "git error for %s (%s): %s",
            project.path_with_namespace,
            mask_token(url),
            (exc.stderr or "").strip(),
        )
        return False
    return True


@dataclass
class SyncResult:
    """Result of a complete mirror run."""

    succeeded: int
    failed: int


def sync_all(client: ProjectSource, config: Config) -> SyncResult:
    """Mirror all (non-archived) projects in parallel."""
    projects = [
        p for p in client.iter_projects() if config.include_archived or not p.archived
    ]
    logger.info("Mirroring %d projects (jobs=%d)", len(projects), config.jobs)

    with ThreadPoolExecutor(max_workers=config.jobs) as executor:
        results = list(executor.map(lambda p: mirror_project(p, config), projects))

    succeeded = sum(results)
    failed = len(results) - succeeded
    logger.info("Done: %d succeeded, %d failed", succeeded, failed)
    return SyncResult(succeeded=succeeded, failed=failed)
