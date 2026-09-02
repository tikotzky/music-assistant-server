"""Tests for the 24six API client."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock

import aiohttp
import pytest
from music_assistant_models.errors import (
    LoginFailed,
    MediaNotFoundError,
    MusicAssistantError,
    ResourceTemporarilyUnavailable,
)

from music_assistant.providers.twentyfour_six.api_client import TwentyFourSixAPIClient
from music_assistant.providers.twentyfour_six.constants import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_SESSION_DATA,
)
from music_assistant.providers.twentyfour_six.provider import TwentyFourSixProvider

SESSION = json.dumps({"token": "tok-1", "device_id": "dev-1"})
PROFILE = {"id": 1, "name": "Parents", "allowed": {"music": True, "podcast": False}}
CREDENTIALS = {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "pw", CONF_PROFILE_ID: "1"}


class _FakeResponse:
    def __init__(self, status: int, body: str = "", json_body: Any = None) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self._body = body
        self._json = json_body

    async def text(self) -> str:
        return self._body

    async def json(self) -> Any:
        if self._json is None:
            raise json.JSONDecodeError("no json", "", 0)
        return self._json


def _setup_values(provider: TwentyFourSixProvider, values: dict[str, Any]) -> None:
    provider.get_setup_value = lambda key, default=None: values.get(key, default)  # type: ignore[method-assign]


def _record_persisted(provider: TwentyFourSixProvider) -> dict[str, str]:
    persisted: dict[str, str] = {}
    provider.api._persist_setup_value = lambda key, value: persisted.__setitem__(key, value)
    return persisted


def _fake_post(response: _FakeResponse) -> Any:
    """Return a fake http_session.post yielding the given response."""

    @asynccontextmanager
    async def post(*_args: Any, **_kwargs: Any) -> Any:
        yield response

    return post


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
    assert provider.api.profile_allows("podcast") is False
    assert provider.api.profile_allows("music") is True
    assert provider.api.profile_allows("stories") is True


@pytest.mark.parametrize(
    ("outcome", "login_expected"),
    [
        ((401, {"message": "Unauthenticated"}), True),
        ((503, None), False),
        (aiohttp.ClientConnectionError("down"), False),
    ],
)
async def test_restore_session_outcomes(
    provider: TwentyFourSixProvider, outcome: Any, login_expected: bool
) -> None:
    """A 401 forces a new login; a server or network error keeps the stored token."""
    _setup_values(provider, {CONF_SESSION_DATA: SESSION})
    provider.api._raw_request = AsyncMock(  # type: ignore[method-assign]
        side_effect=outcome if isinstance(outcome, Exception) else None,
        return_value=None if isinstance(outcome, Exception) else outcome,
    )
    provider.api.login = AsyncMock()  # type: ignore[method-assign]
    _record_persisted(provider)

    await provider.api.ensure_logged_in()

    assert provider.api.login.await_count == (1 if login_expected else 0)
    if not login_expected:
        assert provider.api._access_token == "tok-1"
        assert provider.api.profile == {}


async def test_missing_session_logs_in(provider: TwentyFourSixProvider) -> None:
    """Without stored session data the client logs in and persists the new session."""
    _setup_values(provider, {})
    persisted = _record_persisted(provider)

    async def fake_login() -> None:
        provider.api._access_token = "tok-2"
        provider.api._device_id = "dev-2"

    provider.api.login = fake_login  # type: ignore[method-assign]
    provider.api._raw_request = AsyncMock()  # type: ignore[method-assign]

    await provider.api.ensure_logged_in()

    provider.api._raw_request.assert_not_awaited()
    assert json.loads(persisted[CONF_SESSION_DATA]) == {"token": "tok-2", "device_id": "dev-2"}


async def test_login_success_persists_device_and_profile(provider: TwentyFourSixProvider) -> None:
    """A login stores the server-assigned device id and the profile with its permissions."""
    _setup_values(provider, {**CREDENTIALS, CONF_DEVICE_ID: "dev-old"})
    persisted = _record_persisted(provider)
    cast("Any", provider.mass).http_session.post = _fake_post(
        _FakeResponse(200, json_body={"token": "tok-3", "device_id": "dev-3", "profile": PROFILE})
    )
    provider.api._register_device = AsyncMock()  # type: ignore[method-assign]

    await provider.api.login()

    assert provider.api._access_token == "tok-3"
    assert provider.api.device_id == "dev-3"
    assert persisted[CONF_DEVICE_ID] == "dev-3"
    assert provider.api.profile == PROFILE
    provider.api._register_device.assert_awaited_once()


@pytest.mark.parametrize(
    ("status", "body", "expected_key"),
    [
        (401, '{"message": "Invalid credentials"}', "login_failed"),
        (422, '{"message": "The pin is incorrect."}', "pin_required"),
    ],
)
async def test_login_failures_carry_translation_keys(
    provider: TwentyFourSixProvider, status: int, body: str, expected_key: str
) -> None:
    """A rejected login raises LoginFailed with a key the setup form can translate."""
    _setup_values(provider, CREDENTIALS)
    _record_persisted(provider)
    cast("Any", provider.mass).http_session.post = _fake_post(_FakeResponse(status, body))

    with pytest.raises(LoginFailed) as excinfo:
        await provider.api.login()
    assert excinfo.value.translation_key == expected_key
    assert excinfo.value.translation_owner == "provider.twentyfour_six"


async def test_login_without_setup_values(provider: TwentyFourSixProvider) -> None:
    """Missing credentials fail before any request is made."""
    _setup_values(provider, {})
    with pytest.raises(LoginFailed):
        await provider.api.login()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (422, '{"message": "The q field is required."}', MusicAssistantError),
        (405, "nope", MusicAssistantError),
        (404, "", MediaNotFoundError),
        (500, "boom", ResourceTemporarilyUnavailable),
        (503, "", ResourceTemporarilyUnavailable),
    ],
)
async def test_error_responses_map_to_errors(
    provider: TwentyFourSixProvider, status: int, body: str, expected: type[Exception]
) -> None:
    """Client errors fail fast with the API message, server errors are retried later."""
    with pytest.raises(expected) as excinfo:
        await provider.api._handle_api_response(
            cast("Any", _FakeResponse(status, body)), "music/search", "tok"
        )
    if status == 422:
        assert "The q field is required." in str(excinfo.value)


@pytest.mark.parametrize(
    ("retry_after", "expected"), [("12", 12), ("garbage", 30), (None, 30), ("0", 30)]
)
async def test_rate_limit_backoff(
    provider: TwentyFourSixProvider, retry_after: str | None, expected: int
) -> None:
    """A 429 backs off for the Retry-After value, or a sane default when it is unusable."""
    response = _FakeResponse(429, "")
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    with pytest.raises(ResourceTemporarilyUnavailable) as excinfo:
        await provider.api._handle_api_response(cast("Any", response), "music/search", "tok")
    assert excinfo.value.backoff_time == expected


async def test_401_triggers_single_relogin(provider: TwentyFourSixProvider) -> None:
    """A 401 re-authenticates once and asks the caller to retry shortly."""
    provider.api._access_token = "old"
    provider.api.login = AsyncMock()  # type: ignore[method-assign]
    _record_persisted(provider)
    with pytest.raises(ResourceTemporarilyUnavailable):
        await provider.api._handle_api_response(
            cast("Any", _FakeResponse(401, "")), "music/artist", "old"
        )
    provider.api.login.assert_awaited_once()
    # a stale caller whose token was already replaced does not log in again
    provider.api._access_token = "new"
    with pytest.raises(ResourceTemporarilyUnavailable):
        await provider.api._handle_api_response(
            cast("Any", _FakeResponse(401, "")), "music/artist", "old"
        )
    provider.api.login.assert_awaited_once()


async def test_list_responses_are_wrapped(provider: TwentyFourSixProvider) -> None:
    """A bare JSON list answer is exposed under the usual data key."""
    result = await provider.api._handle_api_response(
        cast("Any", _FakeResponse(200, json_body=[{"id": 1}])), "music/content/recommended"
    )
    assert result == {"data": [{"id": 1}]}
    assert await provider.api._handle_api_response(cast("Any", _FakeResponse(204)), "x") == {}


async def test_log_playback_sends_app_fields_and_warns_on_failure(
    provider: TwentyFourSixProvider, caplog: pytest.LogCaptureFixture
) -> None:
    """The play log carries the app's fields; a failure is logged, never raised."""
    provider.api._device_id = "dev-1"
    provider.api._request = AsyncMock(return_value={})  # type: ignore[method-assign]
    # the fixture stubs log_playback for the provider tests, exercise the real method here
    log_playback = TwentyFourSixAPIClient.log_playback.__get__(provider.api)
    await log_playback("33", seconds=42, current=42)
    call = cast("Any", provider.api._request.await_args)
    params = call.kwargs["params"]
    assert call.args == ("POST", "content/33/log")
    assert params["seconds"] == "42"
    assert params["current"] == "42"
    assert params["device_id"] == "dev-1"
    assert params["is_offline"] == "0"
    assert len(params["streamed_at"]) == len("2026-09-02 00:00:00")

    provider.api._request = AsyncMock(side_effect=MusicAssistantError("API error 422"))  # type: ignore[method-assign]
    with caplog.at_level("WARNING"):
        await log_playback("33", seconds=1, current=1)
    assert "Could not log the play of 33" in caplog.text
