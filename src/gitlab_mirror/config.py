"""Runtime configuration from CLI arguments and environment variables."""

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

ENV_GITLAB_URL = "GITLAB_URL"
ENV_TOKEN = "GITLAB_TOKEN"
ENV_TARGET_DIR = "GITLAB_MIRROR_DIR"


@dataclass(frozen=True)
class Config:
    """Fully resolved configuration for a single mirror run."""

    gitlab_url: str
    token: str
    target_dir: Path
    use_ssh: bool
    include_archived: bool
    jobs: int
    timeout: float


def build_config(args: argparse.Namespace) -> Config:
    """Build the config from argparse arguments, falling back to env variables.

    CLI arguments take precedence over environment variables. A ValueError is
    raised if a required value is missing.
    """
    gitlab_url = args.gitlab_url or os.environ.get(ENV_GITLAB_URL)
    token = args.token or os.environ.get(ENV_TOKEN)
    target_dir = args.target_dir or os.environ.get(ENV_TARGET_DIR)

    missing = [
        name
        for name, value in (
            ("--gitlab-url", gitlab_url),
            ("--token", token),
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
    assert gitlab_url is not None and token is not None and target_dir is not None

    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1")

    return Config(
        gitlab_url=gitlab_url.rstrip("/"),
        token=token,
        target_dir=Path(target_dir).expanduser(),
        use_ssh=args.ssh,
        include_archived=args.include_archived,
        jobs=args.jobs,
        timeout=args.timeout,
    )
