"""Forge providers and the factory that selects one from the config."""

from forge_mirror.config import Config
from forge_mirror.providers.base import Provider
from forge_mirror.providers.forgejo import ForgejoProvider
from forge_mirror.providers.github import GitHubProvider
from forge_mirror.providers.gitlab import GitLabProvider

PROVIDERS = ("gitlab", "github", "forgejo")


def create_provider(config: Config) -> Provider:
    """Instantiate the provider selected in the config."""
    if config.provider == "gitlab":
        return GitLabProvider(config.base_url, config.token, config.timeout)
    if config.provider == "github":
        return GitHubProvider(config.base_url, config.token, config.timeout, config.owner)
    if config.provider == "forgejo":
        return ForgejoProvider(config.base_url, config.token, config.timeout)
    raise ValueError(f"Unknown provider: {config.provider}")
