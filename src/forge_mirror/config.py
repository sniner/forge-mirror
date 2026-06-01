"""Runtime configuration from CLI arguments and environment variables."""

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path

ENV_TARGET_DIR = "FORGE_MIRROR_DIR"

# Provider-specific environment variables for token and base URL.
_ENV_TOKEN = {"gitlab": "GITLAB_TOKEN", "github": "GITHUB_TOKEN"}
_ENV_URL = {"gitlab": "GITLAB_URL", "github": "GITHUB_URL"}

# GitHub has a single well-known API endpoint; GitLab is self-hosted.
_DEFAULT_URL = {"github": "https://api.github.com"}


@dataclass(frozen=True)
class Config:
    """Fully resolved configuration for a single mirror run."""

    provider: str
    base_url: str
    token: str
    target_dir: Path
    owner: str | None
    use_ssh: bool
    include_archived: bool
    jobs: int
    timeout: float


def build_config(args: argparse.Namespace) -> Config:
    """Build the config from argparse arguments, falling back to env variables.

    CLI arguments take precedence over environment variables. A ValueError is
    raised if a required value is missing or an option is used incorrectly.
    """
    provider = args.provider
    token = args.token or os.environ.get(_ENV_TOKEN[provider])
    base_url = (
        args.url or os.environ.get(_ENV_URL[provider]) or _DEFAULT_URL.get(provider)
    )
    target_dir = args.target_dir or os.environ.get(ENV_TARGET_DIR)

    missing = [
        name
        for name, value in (
            ("--token", token),
            ("--url", base_url),
            ("--target-dir", target_dir),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing required options: "
            + ", ".join(missing)
            + " (set via argument or environment variable)"
        )
    assert token is not None and base_url is not None and target_dir is not None

    # github.com's API lives on api.github.com, not github.com itself (only
    # GitHub Enterprise serves its API from the web host, under /api/v3).
    if provider == "github":
        base_url = re.sub(
            r"^(https?://)(www\.)?github\.com/?$",
            r"\1api.github.com",
            base_url,
            flags=re.IGNORECASE,
        )

    if args.owner and provider != "github":
        raise ValueError("--owner is only supported with --provider github")

    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1")

    return Config(
        provider=provider,
        base_url=base_url.rstrip("/"),
        token=token,
        target_dir=Path(target_dir).expanduser(),
        owner=args.owner,
        use_ssh=args.ssh,
        include_archived=args.include_archived,
        jobs=args.jobs,
        timeout=args.timeout,
    )
