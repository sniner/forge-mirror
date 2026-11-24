import logging

import httpx
import pytest
import respx

from forge_mirror.cli import main

URL = "https://forge.example"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("FORGE_MIRROR_PROVIDER", "FORGE_MIRROR_URL", "FORGE_MIRROR_TOKEN"):
        monkeypatch.delenv(var, raising=False)


@respx.mock
def test_an_unreachable_forge_is_reported_during_detection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    respx.route(host="forge.example").mock(side_effect=httpx.ConnectTimeout)

    assert main(["--url", URL, "--token", "t", "--list"]) == 1

    assert "Detecting the forge at https://forge.example" in caplog.text
    assert "Cannot reach https://forge.example: no connection within 10 seconds" in (
        caplog.text
    )


@respx.mock
def test_an_unreachable_named_forge_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    respx.route(host="forge.example").mock(side_effect=httpx.ConnectTimeout)

    argv = ["--provider", "gitlab", "--url", URL, "--token", "t", "--list"]
    assert main(argv) == 1

    assert "Cannot reach https://forge.example: no connection within 10 seconds" in (
        caplog.text
    )


@respx.mock
def test_a_shorter_timeout_also_limits_the_wait_for_a_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.route(host="forge.example").mock(side_effect=httpx.ConnectTimeout)

    assert main(["--url", URL, "--token", "t", "--list", "--timeout", "2.5"]) == 1

    assert "no connection within 2.5 seconds" in caplog.text
