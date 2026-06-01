import argparse
from pathlib import Path

import pytest

from gitlab_mirror.config import build_config


def make_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "gitlab_url": None,
        "token": None,
        "target_dir": None,
        "ssh": False,
        "include_archived": False,
        "jobs": 4,
        "timeout": 30.0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_args_take_precedence_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://env.example")
    monkeypatch.setenv("GITLAB_TOKEN", "env-token")
    monkeypatch.setenv("GITLAB_MIRROR_DIR", "/env/dir")

    config = build_config(
        make_args(
            gitlab_url="https://arg.example",
            token="arg-token",
            target_dir="/arg/dir",
        )
    )

    assert config.gitlab_url == "https://arg.example"
    assert config.token == "arg-token"
    assert config.target_dir == Path("/arg/dir")


def test_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://env.example")
    monkeypatch.setenv("GITLAB_TOKEN", "env-token")
    monkeypatch.setenv("GITLAB_MIRROR_DIR", "/env/dir")

    config = build_config(make_args())

    assert config.gitlab_url == "https://env.example"
    assert config.token == "env-token"
    assert config.target_dir == Path("/env/dir")


def test_url_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITLAB_URL", raising=False)
    config = build_config(
        make_args(
            gitlab_url="https://gl.example/",
            token="t",
            target_dir="/d",
        )
    )
    assert config.gitlab_url == "https://gl.example"


def test_missing_required_values_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GITLAB_URL", "GITLAB_TOKEN", "GITLAB_MIRROR_DIR"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValueError, match="Missing required options"):
        build_config(make_args())


def test_invalid_jobs_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="--jobs"):
        build_config(
            make_args(
                gitlab_url="https://gl.example",
                token="t",
                target_dir="/d",
                jobs=0,
            )
        )
