"""Tests for the 24six setup flow."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from music_assistant_models.enums import FlowStepType

from music_assistant.models.setup_flow import SetupFlowContext, SetupFlowError, SetupSession
from music_assistant.providers.twentyfour_six.constants import (
    CONF_DEVICE_ID,
    CONF_DEVICE_SERIAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_PROFILE_PIN,
)
from music_assistant.providers.twentyfour_six.setup_flow import ProfileLookupError, run_setup

PROFILES: list[dict[str, Any]] = [
    {"id": 1, "name": "Family", "pin_required": False},
    {"id": 2, "name": "Parents", "pin_required": True},
]
FETCH_PROFILES = "music_assistant.providers.twentyfour_six.setup_flow.fetch_profiles"


def _make_session(finish_handler: Any, setup_data: dict[str, Any] | None = None) -> SetupSession:
    """Build a SetupSession backed by a Mock mass for driving run_setup directly."""
    context = SetupFlowContext(
        kind="reconfigure" if setup_data else "setup",
        reason="user",
        domain="twentyfour_six",
        setup_data=setup_data or {},
    )
    return SetupSession(Mock(), "flow-test", context, finish_handler)


async def _wait_for(predicate: Any, timeout: float = 5.0) -> Any:
    """Wait until the predicate returns truthy (or fail the test)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


async def _wait_for_form(session: SetupSession, step_id: str, with_errors: bool = False) -> Any:
    """Wait until the flow publishes the FORM step with the given step_id."""
    return await _wait_for(
        lambda: (
            session.current_step
            if session.current_step
            and session.current_step.type == FlowStepType.FORM
            and session.current_step.step_id == step_id
            and (session.current_step.errors if with_errors else True)
            else None
        )
    )


async def test_setup_collects_credentials_and_profile() -> None:
    """The flow asks for credentials, lists the profiles and persists the selection."""
    collected: dict[str, Any] = {}

    async def finish_handler(_session: SetupSession, values: dict[str, Any]) -> dict[str, str]:
        collected.update(values)
        return {"instance_id": "twentyfour_six--test"}

    session = _make_session(finish_handler)
    with patch(FETCH_PROFILES, AsyncMock(return_value=PROFILES)) as fetch_mock:
        task = asyncio.create_task(run_setup(session))
        await _wait_for_form(session, "user")
        session.handle_submit({CONF_EMAIL: "me@example.com", CONF_PASSWORD: "secret"})

        step = await _wait_for_form(session, "profile")
        profile_entry = next(entry for entry in step.entries if entry.key == CONF_PROFILE_ID)
        assert [option.value for option in profile_entry.options] == ["1", "2"]
        assert [option.title for option in profile_entry.options] == [
            "Family",
            "Parents (PIN required)",
        ]
        assert profile_entry.value == "1"
        assert any(entry.key == CONF_PROFILE_PIN for entry in step.entries)
        session.handle_submit({CONF_PROFILE_ID: "2", CONF_PROFILE_PIN: "1234"})
        await _wait_for(lambda: session.finished)
        await task

    fetch_mock.assert_awaited_once()
    assert fetch_mock.await_args is not None
    assert fetch_mock.await_args.args[1:3] == ("me@example.com", "secret")
    assert collected[CONF_EMAIL] == "me@example.com"
    assert collected[CONF_PASSWORD] == "secret"
    assert collected[CONF_PROFILE_ID] == "2"
    assert collected[CONF_PROFILE_PIN] == "1234"
    assert collected[CONF_DEVICE_ID] == fetch_mock.await_args.args[3]
    assert CONF_DEVICE_SERIAL not in collected


async def test_setup_retries_credentials_after_failed_lookup() -> None:
    """A failed profile lookup re-shows the credentials form with the error."""
    collected: dict[str, Any] = {}

    async def finish_handler(_session: SetupSession, values: dict[str, Any]) -> dict[str, str]:
        collected.update(values)
        return {"instance_id": "twentyfour_six--test"}

    session = _make_session(finish_handler)
    fetch_mock = AsyncMock(side_effect=[ProfileLookupError("login_failed"), PROFILES])
    with patch(FETCH_PROFILES, fetch_mock):
        task = asyncio.create_task(run_setup(session))
        await _wait_for_form(session, "user")
        session.handle_submit({CONF_EMAIL: "me@example.com", CONF_PASSWORD: "wrong"})

        step = await _wait_for_form(session, "user", with_errors=True)
        assert step.errors == {"base": "login_failed"}
        session.handle_submit({CONF_EMAIL: "me@example.com", CONF_PASSWORD: "right"})

        await _wait_for_form(session, "profile")
        session.handle_submit({CONF_PROFILE_ID: "1"})
        await _wait_for(lambda: session.finished)
        await task

    assert fetch_mock.await_count == 2
    assert collected[CONF_PASSWORD] == "right"
    assert collected[CONF_PROFILE_PIN] == ""


async def test_reconfigure_keeps_device_and_retries_profile_on_failed_finish() -> None:
    """A reconfigure prefills the previous profile and keeps the device identity."""
    attempts: list[dict[str, Any]] = []

    async def finish_handler(_session: SetupSession, values: dict[str, Any]) -> dict[str, str]:
        attempts.append(dict(values))
        if len(attempts) == 1:
            raise SetupFlowError("Provider did not load", translation_key="pin_required")
        return {"instance_id": "twentyfour_six--test"}

    session = _make_session(
        finish_handler,
        {
            CONF_EMAIL: "me@example.com",
            CONF_PROFILE_ID: "2",
            CONF_DEVICE_ID: "server-device-id",
            CONF_DEVICE_SERIAL: "SERIAL-1",
        },
    )
    with patch(FETCH_PROFILES, AsyncMock(return_value=PROFILES)) as fetch_mock:
        task = asyncio.create_task(run_setup(session))
        step = await _wait_for_form(session, "user")
        email_entry = next(entry for entry in step.entries if entry.key == CONF_EMAIL)
        assert email_entry.value == "me@example.com"
        session.handle_submit({CONF_EMAIL: "me@example.com", CONF_PASSWORD: "secret"})

        step = await _wait_for_form(session, "profile")
        profile_entry = next(entry for entry in step.entries if entry.key == CONF_PROFILE_ID)
        assert profile_entry.value == "2"
        session.handle_submit({CONF_PROFILE_ID: "2"})

        step = await _wait_for_form(session, "profile", with_errors=True)
        assert step.errors == {"base": "pin_required"}
        session.handle_submit({CONF_PROFILE_ID: "2", CONF_PROFILE_PIN: "0000"})
        await _wait_for(lambda: session.finished)
        await task

    assert fetch_mock.await_args is not None
    assert fetch_mock.await_args.args[3] == "server-device-id"
    assert len(attempts) == 2
    assert attempts[1][CONF_PROFILE_PIN] == "0000"
    assert attempts[1][CONF_DEVICE_ID] == "server-device-id"
    assert attempts[1][CONF_DEVICE_SERIAL] == "SERIAL-1"
