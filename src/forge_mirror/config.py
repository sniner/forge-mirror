"""Runtime configuration from CLI arguments and environment variables."""

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

ENV_PROVIDER = "FORGE_MIRROR_PROVIDER"
ENV_URL = "FORGE_MIRROR_URL"
ENV_TOKEN = "FORGE_MIRROR_TOKEN"
ENV_TARGET_DIR = "FORGE_MIRROR_DIR"

# Stands in for the provider until the forge has said which one it is.
AUTO = "auto"

# GitHub has a single well-known API endpoint; the others are self-hosted, and
# without a named provider there is nothing to guess a URL from.
_DEFAULT_URL = {"github": "https://api.github.com"}


@dataclass(frozen=True)
class Config:
    """Fully resolved configuration for a single mirror run."""

    provider: str
    base_url: str
    token: str
    # None only when list_only is set: a listing has nowhere to write.
    target_dir: Path | None
    owner: str | None
    list_only: bool
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
            + " -- pass the argument or set the environment variable named after it"
        )
    assert token is not None and base_url is not None

    if args.list and args.prune:
        raise ValueError(
            "--list writes nothing, so --prune would have nothing to delete "
            "-- drop one of the two"
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
        use_ssh=args.ssh,
        include_archived=args.include_archived,
        prune=args.prune,
        prune_limit=args.prune_limit,
        jobs=args.jobs,
        timeout=args.timeout,
    )
