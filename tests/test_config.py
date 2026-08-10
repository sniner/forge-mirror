import argparse
from pathlib import Path

import pytest

from forge_mirror.config import build_config


def make_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "provider": "gitlab",
        "url": None,
        "token": None,
        "target_dir": None,
        "owner": None,
        "ssh": False,
        "include_archived": False,
        "prune": False,
        "prune_limit": 10,
        "jobs": 4,
        "timeout": 30.0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GITLAB_URL", "GITHUB_URL", "GITLAB_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("FORGE_MIRROR_DIR", raising=False)


def test_args_take_precedence_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://env.example")
    monkeypatch.setenv("GITLAB_TOKEN", "env-token")
    monkeypatch.setenv("FORGE_MIRROR_DIR", "/env/dir")

    config = build_config(
        make_args(url="https://arg.example", token="arg-token", target_dir="/arg/dir")
    )

    assert config.base_url == "https://arg.example"
    assert config.token == "arg-token"
    assert config.target_dir == Path("/arg/dir")


def test_falls_back_to_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("GITLAB_URL", "https://env.example")
    monkeypatch.setenv("GITLAB_TOKEN", "env-token")
    monkeypatch.setenv("FORGE_MIRROR_DIR", "/env/dir")

    config = build_config(make_args())

    assert config.base_url == "https://env.example"
    assert config.token == "env-token"
    assert config.target_dir == Path("/env/dir")


def test_github_token_env_is_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("GITLAB_TOKEN", "gl-token")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")

    config = build_config(make_args(provider="github", target_dir="/d"))

    assert config.token == "gh-token"


def test_github_defaults_to_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    config = build_config(make_args(provider="github", token="t", target_dir="/d"))
    assert config.base_url == "https://api.github.com"


@pytest.mark.parametrize(
    "given",
    [
        "https://github.com",
        "https://github.com/",
        "https://www.github.com",
        "http://github.com",
    ],
)
def test_github_web_host_is_rewritten_to_api(
    monkeypatch: pytest.MonkeyPatch, given: str
) -> None:
    _clear_env(monkeypatch)
    config = build_config(
        make_args(provider="github", url=given, token="t", target_dir="/d")
    )
    assert config.base_url.endswith("api.github.com")


def test_github_enterprise_url_is_left_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    config = build_config(
        make_args(
            provider="github",
            url="https://ghe.example/api/v3",
            token="t",
            target_dir="/d",
        )
    )
    assert config.base_url == "https://ghe.example/api/v3"


def test_url_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    config = build_config(
        make_args(url="https://gl.example/", token="t", target_dir="/d")
    )
    assert config.base_url == "https://gl.example"


def test_missing_required_values_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValueError, match="Missing required options"):
        build_config(make_args())


def test_gitlab_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValueError, match="--url"):
        build_config(make_args(token="t", target_dir="/d"))


def test_owner_only_allowed_for_github(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValueError, match="--owner"):
        build_config(
            make_args(url="https://gl.example", token="t", target_dir="/d", owner="x")
        )


def test_invalid_jobs_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValueError, match="--jobs"):
        build_config(
            make_args(url="https://gl.example", token="t", target_dir="/d", jobs=0)
        )


def test_negative_prune_limit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValueError, match="--prune-limit"):
        build_config(
            make_args(
                url="https://gl.example",
                token="t",
                target_dir="/d",
                prune_limit=-1,
            )
        )


def test_prune_limit_zero_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    config = build_config(
        make_args(url="https://gl.example", token="t", target_dir="/d", prune_limit=0)
    )
    assert config.prune_limit == 0
