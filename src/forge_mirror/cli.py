"""Command-line entry point for forge-mirror."""

import argparse
import logging

import httpx

from forge_mirror import __version__
from forge_mirror.config import build_config
from forge_mirror.mirror import sync_all
from forge_mirror.providers import PROVIDERS, create_provider
from forge_mirror.providers.base import describe_http_error

logger = logging.getLogger("forge_mirror")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge-mirror",
        description="Mirror all repositories of a Git forge (GitLab, GitHub or "
        "Forgejo) as bare mirrors and update existing ones.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        default="gitlab",
        help="Forge to mirror from (default: gitlab)",
    )
    parser.add_argument(
        "--url",
        help="Base URL of the forge API (env: GITLAB_URL/GITHUB_URL/FORGEJO_URL; "
        "GitHub defaults to https://api.github.com)",
    )
    parser.add_argument(
        "--token",
        help="Personal/project access token "
        "(env: GITLAB_TOKEN/GITHUB_TOKEN/FORGEJO_TOKEN)",
    )
    parser.add_argument(
        "-d",
        "--target-dir",
        help="Target directory for the mirrors (env: FORGE_MIRROR_DIR)",
    )
    parser.add_argument(
        "--owner",
        help="Restrict to a single GitHub user or organization "
        "(GitHub only; default: all visible repositories)",
    )
    parser.add_argument(
        "--ssh",
        action="store_true",
        help="Use SSH URLs instead of HTTPS+token for cloning",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Also mirror archived repositories",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete mirrors whose repository is gone from the forge; "
        "without it they are only reported",
    )
    parser.add_argument(
        "--prune-limit",
        type=int,
        default=10,
        metavar="N",
        help="Cancel the whole prune, deleting nothing, when more than N mirrors "
        "would go (default: 10, 0 turns the check off)",
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
    """Entry point. Returns 0 if all repositories were mirrored successfully and
    no stale mirror was left behind, otherwise the number of failures (capped at
    125)."""
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
        with create_provider(config) as provider:
            result = sync_all(provider, config)
    except httpx.HTTPStatusError as exc:
        logger.error("%s API error: %s", config.provider, describe_http_error(exc))
        return 1
    except httpx.HTTPError as exc:
        logger.error("%s API error: %s", config.provider, exc)
        return 1

    return min(result.failed + result.unremoved, 125)
