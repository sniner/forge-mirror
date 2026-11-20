"""Command-line entry point for forge-mirror."""

import argparse
import logging

import httpx

from forge_mirror import __version__
from forge_mirror.config import build_config
from forge_mirror.mirror import dry_run, list_repos, sync_all
from forge_mirror.providers import PROVIDER_CHOICES, create_provider
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
        choices=PROVIDER_CHOICES,
        default=None,
        help="Forge to mirror from (env: FORGE_MIRROR_PROVIDER; default: auto, "
        "which detects the forge at --url)",
    )
    parser.add_argument(
        "--url",
        help="Base URL of the forge API (env: FORGE_MIRROR_URL; with "
        "--provider github it defaults to https://api.github.com)",
    )
    parser.add_argument(
        "--token",
        help="Personal/project access token (env: FORGE_MIRROR_TOKEN)",
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
        "--list",
        action="store_true",
        help="List the repositories a run would mirror, one per line, and exit; "
        "--target-dir is not needed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what a run would clone, update and (with --prune) delete, "
        "change nothing",
    )
    parser.add_argument(
        "--ssh",
        action="store_true",
        help="Use SSH instead of HTTPS with the token, also for existing mirrors",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Also mirror archived repositories",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete mirrors whose repository no longer exists on the forge; "
        "without it they are only reported",
    )
    parser.add_argument(
        "--prune-limit",
        type=int,
        default=10,
        metavar="N",
        help="Delete nothing when more than N mirrors would be deleted "
        "(default: 10, 0 disables the check)",
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
    """Entry point. Returns 0 if all repositories were mirrored and --prune
    deleted every mirror it had to, otherwise the number of failures (at most
    125)."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # httpx logs every request at INFO. Detection requests the endpoints of
    # forges that are not there, and their 404 would look like an error.
    logging.getLogger("httpx").setLevel(
        logging.DEBUG if args.verbose else logging.WARNING
    )

    try:
        config = build_config(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    # Handled apart from the run below: until the forge is known, an error
    # message cannot name it, and detection writes its own error messages.
    try:
        provider = create_provider(config)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except httpx.HTTPError as exc:
        logger.error("Cannot reach %s: %s", config.base_url, exc)
        return 1

    try:
        with provider:
            if config.list_only:
                list_repos(provider, config)
                return 0
            if config.dry_run:
                dry_run(provider, config)
                return 0
            result = sync_all(provider, config)
    except httpx.HTTPStatusError as exc:
        logger.error("%s API error: %s", provider.name, describe_http_error(exc))
        return 1
    except httpx.HTTPError as exc:
        logger.error("%s API error: %s", provider.name, exc)
        return 1

    return min(result.failed + result.unremoved, 125)
