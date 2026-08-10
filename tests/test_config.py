import argparse
from pathlib import Path

import pytest

from forge_mirror.config import build_config

ENV_VARS = (
    "FORGE_MIRROR_PROVIDER",
    "FORGE_MIRROR_URL",
    "FORGE_MIRROR_TOKEN",
    "FORGE_MIRROR_DIR",
)


def make_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "provider": None,
        "url": None,
        "token": None,
        "target_dir": None,
        "owner": None,
        "list": False,
        "dry_run": False,
        "ssh": False,
        "include_archived": False,
        "prune": False,
        "prune_limit": 10,
        "jobs": 4,
        "timeout": 30.0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_args_take_precedence_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_MIRROR_PROVIDER", "forgejo")
    monkeypatch.setenv("FORGE_MIRROR_URL", "https://env.example")
    monkeypatch.setenv("FORGE_MIRROR_TOKEN", "env-token")
    monkeypatch.setenv("FORGE_MIRROR_DIR", "/env/dir")

    config = build_config(
        make_args(
            provider="gitlab",
            url="https://arg.example",
            token="arg-token",
            target_dir="/arg/dir",
        )
    )

    assert config.provider == "gitlab"
    assert config.base_url == "https://arg.example"
    assert config.token == "arg-token"
    assert config.target_dir == Path("/arg/dir")


def test_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_MIRROR_PROVIDER", "forgejo")
    monkeypatch.setenv("FORGE_MIRROR_URL", "https://env.example")
    monkeypatch.setenv("FORGE_MIRROR_TOKEN", "env-token")
    monkeypatch.setenv("FORGE_MIRROR_DIR", "/env/dir")

    config = build_config(make_args())

    assert config.provider == "forgejo"
    assert config.base_url == "https://env.example"
    assert config.token == "env-token"
    assert config.target_dir == Path("/env/dir")


def test_provider_defaults_to_auto() -> None:
    config = build_config(make_args(url="https://gl.example", token="t", target_dir="/d"))
    assert config.provider == "auto"


def test_auto_requires_url() -> None:
    with pytest.raises(ValueError, match="--url"):
        build_config(make_args(token="t", target_dir="/d"))


def test_forgejo_requires_url() -> None:
    with pytest.raises(ValueError, match="--url"):
        build_config(make_args(provider="forgejo", token="t", target_dir="/d"))


def test_github_defaults_to_public_api() -> None:
    config = build_config(make_args(provider="github", token="t", target_dir="/d"))
    assert config.base_url == "https://api.github.com"


def test_url_is_normalised() -> None:
    config = build_config(
        make_args(url="https://gl.example/", token="t", target_dir="/d")
    )
    assert config.base_url == "https://gl.example"


def test_missing_required_values_name_their_env_variable() -> None:
    with pytest.raises(ValueError, match="Missing required options") as caught:
        build_config(make_args())

    message = str(caught.value)
    assert "--token (FORGE_MIRROR_TOKEN)" in message
    assert "--url (FORGE_MIRROR_URL)" in message
    assert "--target-dir (FORGE_MIRROR_DIR)" in message


def test_list_does_not_need_a_target_directory() -> None:
    config = build_config(make_args(list=True, url="https://gl.example", token="t"))

    assert config.list_only is True
    assert config.target_dir is None


def test_target_dir_is_still_required_without_list() -> None:
    with pytest.raises(ValueError, match="--target-dir"):
        build_config(make_args(url="https://gl.example", token="t"))


def test_list_and_prune_together_are_refused() -> None:
    with pytest.raises(ValueError, match="--prune"):
        build_config(
            make_args(list=True, prune=True, url="https://gl.example", token="t")
        )


def test_list_and_dry_run_together_are_refused() -> None:
    with pytest.raises(ValueError, match="pick the question"):
        build_config(
            make_args(list=True, dry_run=True, url="https://gl.example", token="t")
        )


def test_dry_run_still_needs_a_target_directory() -> None:
    with pytest.raises(ValueError, match="--target-dir"):
        build_config(make_args(dry_run=True, url="https://gl.example", token="t"))


def test_dry_run_and_prune_are_a_valid_pair() -> None:
    config = build_config(
        make_args(
            dry_run=True, prune=True, url="https://gl.example", token="t", target_dir="/d"
        )
    )

    assert config.dry_run is True
    assert config.prune is True


def test_invalid_jobs_raises() -> None:
    with pytest.raises(ValueError, match="--jobs"):
        build_config(
            make_args(url="https://gl.example", token="t", target_dir="/d", jobs=0)
        )


def test_negative_prune_limit_raises() -> None:
    with pytest.raises(ValueError, match="--prune-limit"):
        build_config(
            make_args(
                url="https://gl.example",
                token="t",
                target_dir="/d",
                prune_limit=-1,
            )
        )


def test_prune_limit_zero_is_allowed() -> None:
    config = build_config(
        make_args(url="https://gl.example", token="t", target_dir="/d", prune_limit=0)
    )
    assert config.prune_limit == 0
