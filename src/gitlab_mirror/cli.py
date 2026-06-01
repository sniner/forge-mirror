"""Command-line entry point for gitlab-mirror."""

import argparse
import logging

import httpx

from gitlab_mirror import __version__
from gitlab_mirror.config import build_config
from gitlab_mirror.gitlab import GitLabClient
from gitlab_mirror.mirror import sync_all

logger = logging.getLogger("gitlab_mirror")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitlab-mirror",
        description="Mirror all repositories of a GitLab instance as bare "
        "mirrors and update existing ones.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--gitlab-url",
        help="Base URL of the GitLab instance (env: GITLAB_URL)",
    )
    parser.add_argument(
        "--token",
        help="Personal/project access token (env: GITLAB_TOKEN)",
    )
    parser.add_argument(
        "-d",
        "--target-dir",
        help="Target directory for the mirrors (env: GITLAB_MIRROR_DIR)",
    )
    parser.add_argument(
        "--ssh",
        action="store_true",
        help="Use SSH URLs instead of HTTPS+token for cloning",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Also mirror archived projects",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=4,
        help="Number of parallel git operations (default: 4)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output (DEBUG level)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 if all repositories were mirrored successfully,
    otherwise the number of failures (capped at 125)."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        config = build_config(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    try:
        with GitLabClient(config.gitlab_url, config.token, config.timeout) as client:
            result = sync_all(client, config)
    except httpx.HTTPError as exc:
        logger.error("GitLab API error: %s", exc)
        return 1

    return min(result.failed, 125)
