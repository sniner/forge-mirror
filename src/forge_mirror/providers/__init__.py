"""Forge providers, and the choice between naming one and letting it identify itself."""

import logging

import httpx

from forge_mirror.config import AUTO, Config
from forge_mirror.providers.base import Provider
from forge_mirror.providers.forgejo import ForgejoProvider
from forge_mirror.providers.github import GitHubProvider
from forge_mirror.providers.gitlab import GitLabProvider

logger = logging.getLogger(__name__)

# Asked in this order; the first forge that answers is the one that is there.
PROVIDER_CLASSES: tuple[type[Provider], ...] = (
    GitLabProvider,
    GitHubProvider,
    ForgejoProvider,
)
PROVIDERS = tuple(cls.name for cls in PROVIDER_CLASSES)
PROVIDER_CHOICES = (AUTO, *PROVIDERS)


def create_provider(config: Config) -> Provider:
    """The provider named in the config, or the one the forge turns out to be."""
    provider = _detect(config) if config.provider == AUTO else _named(config)
    if config.owner is not None and provider.name != GitHubProvider.name:
        provider.close()
        raise ValueError(
            f"--owner names a GitHub user or organisation, and {provider.base_url} "
            f"is {provider.name} -- drop it to mirror everything the token sees"
        )
    logger.info("Forge is %s at %s", provider.name, provider.base_url)
    return provider


def _named(config: Config) -> Provider:
    """The provider the user asked for by name."""
    for cls in PROVIDER_CLASSES:
        if cls.name == config.provider:
            return cls.from_config(config)
    raise ValueError(
        f"Unknown forge {config.provider!r} -- name one of "
        f"{', '.join(PROVIDER_CHOICES)} with --provider"
    )


def _detect(config: Config) -> Provider:
    """Ask each forge in turn whether the repositories at the URL are its own.

    Every candidate asks with its own authentication scheme on its own listing
    endpoint, so the one that answers is the one that will work; to the others
    the request is for a route they do not serve, and they say so with a 404.
    """
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

    # Only one forge refusing identifies it, which is worth saying. Several mean
    # something in front of them is answering, and naming them all would lie.
    if len(refused) == 1:
        raise ValueError(
            f"{config.base_url} is {refused[0]}, but the token may not list "
            "repositories there -- check that it is valid and carries the "
            "documented scopes"
        )
    if refused:
        raise ValueError(
            f"{config.base_url} refuses the token -- check that it is valid and "
            "carries the documented scopes"
        )
    raise ValueError(
        f"No GitLab, GitHub or Forgejo API answers at {config.base_url} -- check "
        "the URL, or name the forge with --provider"
    )
