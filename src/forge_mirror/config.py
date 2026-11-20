"""Runtime configuration from CLI arguments and environment variables."""

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

ENV_PROVIDER = "FORGE_MIRROR_PROVIDER"
ENV_URL = "FORGE_MIRROR_URL"
ENV_TOKEN = "FORGE_MIRROR_TOKEN"
ENV_TARGET_DIR = "FORGE_MIRROR_DIR"

# Provider value for detecting the forge from its API.
AUTO = "auto"

# GitHub has a single public API URL. GitLab and Forgejo are self-hosted, and
# with detection the forge is not known yet, so there is no default for them.
_DEFAULT_URL = {"github": "https://api.github.com"}


@dataclass(frozen=True)
class Config:
    """Fully resolved configuration for a single mirror run."""

    provider: str
    base_url: str
    token: str
    # None only with list_only, which writes nothing.
    target_dir: Path | None
    owner: str | None
    list_only: bool
    dry_run: bool
    use_ssh: bool
    include_archived: bool
    prune: bool
    prune_limit: int
    jobs: int
    timeout: float


def build_config(args: argparse.Namespace) -> Config:
    """Build the config from argparse arguments, falling back to env variables.

    CLI arguments take precedence over environment variables. A ValueError is
    raised if a required value is missing or an option is used incorrectly.
    """
    provider = args.provider or os.environ.get(ENV_PROVIDER) or AUTO
    token = args.token or os.environ.get(ENV_TOKEN)
    base_url = args.url or os.environ.get(ENV_URL) or _DEFAULT_URL.get(provider)
    target_dir = args.target_dir or os.environ.get(ENV_TARGET_DIR)

    required = [("--token", ENV_TOKEN, token), ("--url", ENV_URL, base_url)]
    if not args.list:
        required.append(("--target-dir", ENV_TARGET_DIR, target_dir))

    missing = [f"{name} ({env})" for name, env, value in required if not value]
    if missing:
        raise ValueError(
            "Missing required options: "
            + ", ".join(missing)
            + "; pass the option or set the environment variable in parentheses"
        )
    assert token is not None and base_url is not None

    if args.list and args.prune:
        raise ValueError(
            "--prune has no effect with --list, which only lists repositories; "
            "drop one of them"
        )

    if args.list and args.dry_run:
        raise ValueError(
            "--list and --dry-run cannot be combined; use --list to see the "
            "repositories, --dry-run to see what a run would change"
        )

    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1")

    if args.prune_limit < 0:
        raise ValueError("--prune-limit must be 0 (no limit) or a positive number")

    return Config(
        provider=provider,
        base_url=base_url.rstrip("/"),
        token=token,
        target_dir=Path(target_dir).expanduser() if target_dir else None,
        owner=args.owner,
        list_only=args.list,
        dry_run=args.dry_run,
        use_ssh=args.ssh,
        include_archived=args.include_archived,
        prune=args.prune,
        prune_limit=args.prune_limit,
        jobs=args.jobs,
        timeout=args.timeout,
    )
