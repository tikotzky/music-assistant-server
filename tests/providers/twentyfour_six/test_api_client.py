"""Tests for the 24six API client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest

from music_assistant.providers.twentyfour_six.constants import CONF_SESSION_DATA
from music_assistant.providers.twentyfour_six.provider import TwentyFourSixProvider

SESSION = json.dumps({"token": "tok-1", "device_id": "dev-1"})
PROFILE = {"id": 1, "name": "Parents", "allowed": {"music": True, "podcast": False}}


def _setup_values(provider: TwentyFourSixProvider, values: dict[str, Any]) -> None:
    provider.get_setup_value = lambda key, default=None: values.get(key, default)  # type: ignore[method-assign]


async def test_restore_session_keeps_profile_permissions(provider: TwentyFourSixProvider) -> None:
    """A valid stored token is restored together with the profile's content permissions."""
    _setup_values(provider, {CONF_SESSION_DATA: SESSION})
    provider.api._raw_request = AsyncMock(return_value=(200, {"profile": PROFILE}))  # type: ignore[method-assign]
    provider.api.login = AsyncMock()  # type: ignore[method-assign]

    await provider.api.ensure_logged_in()

    provider.api._raw_request.assert_awaited_once_with("GET", "profile")
    provider.api.login.assert_not_awaited()
    assert provider.api._access_token == "tok-1"
    assert provider.api.device_id == "dev-1"
    assert provider.api.profile == PROFILE
    assert provider._profile_allows("podcast") is False


@pytest.mark.parametrize(
    ("outcome", "login_expected"),
    [
        ((401, {"message": "Unauthenticated"}), True),
        ((503, None), False),
        (aiohttp.ClientConnectionError("down"), False),
    ],
)
async def test_restore_session_outcomes(
    provider: TwentyFourSixProvider,
    outcome: Any,
    login_expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 401 forces a new login; a server or network error keeps the stored token."""
    _setup_values(provider, {CONF_SESSION_DATA: SESSION})
    provider.api._raw_request = AsyncMock(  # type: ignore[method-assign]
        side_effect=outcome if isinstance(outcome, Exception) else None,
        return_value=None if isinstance(outcome, Exception) else outcome,
    )
    provider.api.login = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(provider, "update_session_data", lambda _data: None)

    await provider.api.ensure_logged_in()

    assert provider.api.login.await_count == (1 if login_expected else 0)
    if not login_expected:
        assert provider.api._access_token == "tok-1"
        assert provider.api.profile == {}


async def test_missing_session_logs_in(
    provider: TwentyFourSixProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without stored session data the client logs in and persists the new session."""
    _setup_values(provider, {})
    persisted: list[str] = []
    monkeypatch.setattr(provider, "update_session_data", persisted.append)

    async def fake_login() -> None:
        provider.api._access_token = "tok-2"
        provider.api._device_id = "dev-2"

    provider.api.login = fake_login  # type: ignore[method-assign]
    provider.api._raw_request = AsyncMock()  # type: ignore[method-assign]

    await provider.api.ensure_logged_in()

    provider.api._raw_request.assert_not_awaited()
    assert json.loads(persisted[0]) == {"token": "tok-2", "device_id": "dev-2"}
