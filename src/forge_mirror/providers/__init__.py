"""Forge providers and the detection of the forge at a URL."""

import logging

import httpx

from forge_mirror.config import AUTO, Config
from forge_mirror.providers.base import Provider
from forge_mirror.providers.forgejo import ForgejoProvider
from forge_mirror.providers.github import GitHubProvider
from forge_mirror.providers.gitlab import GitLabProvider

logger = logging.getLogger(__name__)

# Detection order; the first forge whose listing endpoint returns a list is used.
PROVIDER_CLASSES: tuple[type[Provider], ...] = (
    GitLabProvider,
    GitHubProvider,
    ForgejoProvider,
)
PROVIDERS = tuple(cls.name for cls in PROVIDER_CLASSES)
PROVIDER_CHOICES = (AUTO, *PROVIDERS)


def create_provider(config: Config) -> Provider:
    """The provider named in the config, or the detected one."""
    provider = _detect(config) if config.provider == AUTO else _named(config)
    if config.owner is not None and provider.name != GitHubProvider.name:
        provider.close()
        raise ValueError(
            f"--owner works only with GitHub, and {provider.base_url} is "
            f"{provider.name}; drop --owner to mirror all repositories the token "
            "can see"
        )
    logger.info("Forge is %s at %s", provider.name, provider.base_url)
    return provider


def _named(config: Config) -> Provider:
    """The provider the user named."""
    for cls in PROVIDER_CLASSES:
        if cls.name == config.provider:
            return cls.from_config(config)
    raise ValueError(
        f"Unknown forge {config.provider!r}; --provider and FORGE_MIRROR_PROVIDER "
        f"take one of {', '.join(PROVIDER_CHOICES)}"
    )


def _detect(config: Config) -> Provider:
    """Probe the listing endpoint of each forge in turn.

    Each probe uses that forge's authentication, so the first forge that returns
    a list is the one at the URL, and listing will work with this token. The
    other forges return 404 for a path they do not serve.
    """
    logger.info("Detecting the forge at %s", config.base_url)
    refused: list[str] = []
    for cls in PROVIDER_CLASSES:
        provider = cls.from_config(config)
        try:
            result = provider.probe()
        except httpx.HTTPError:
            provider.close()
            raise
        if result.accepted:
            return provider
        provider.close()
        logger.debug("%s is not %s (HTTP %d)", config.base_url, cls.name, result.status)
        if result.refused:
            refused.append(cls.name)

    # A single rejecting forge is the forge at the URL. If several reject the
    # token, a proxy in front of the server probably answered, and the forge is
    # unknown.
    if len(refused) == 1:
        raise ValueError(
            f"{config.base_url} is {refused[0]}, but rejects the token; check that "
            "the token is valid and has the scopes listed in the README"
        )
    if refused:
        raise ValueError(
            f"{config.base_url} rejects the token; check that it is valid and has "
            "the scopes listed in the README"
        )
    raise ValueError(
        f"No GitLab, GitHub or Forgejo API found at {config.base_url}; check the "
        "URL, or name the forge with --provider"
    )
