"""Setup flow for the 24six provider: account credentials, then a profile (with PIN)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import aiohttp
from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType

from music_assistant.models.setup_flow import SetupFlowError

from .constants import (
    API_BASE_URL,
    CONF_DEVICE_ID,
    CONF_DEVICE_SERIAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_PROFILE_PIN,
)
from .helpers import build_api_headers

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType

    from music_assistant.mass import MusicAssistant
    from music_assistant.models.setup_flow import SetupSession

_CREDENTIAL_ENTRIES = (
    ConfigEntry(key=CONF_EMAIL, type=ConfigEntryType.STRING, required=True),
    ConfigEntry(key=CONF_PASSWORD, type=ConfigEntryType.SECURE_STRING, required=True),
)


class ProfileLookupError(Exception):
    """Raised when the profiles of an account could not be fetched."""

    def __init__(self, reason: str) -> None:
        """
        Initialize the error.

        :param reason: Error slug (resolved from the provider's strings) shown on the form.
        """
        super().__init__(reason)
        self.reason = reason


async def run_setup(session: SetupSession) -> None:
    """
    Run the setup flow: collect the credentials, pick a profile and create the provider.

    :param session: The setup flow session used to interact with the user.
    """
    setup_data = dict(session.context.setup_data)
    # the device id is assigned by the server on the first login; until then a
    # random one identifies this Music Assistant instance towards the API
    device_id = str(setup_data.get(CONF_DEVICE_ID) or uuid.uuid4())
    errors: dict[str, str] | None = None
    while True:
        credentials = await session.form(
            [
                replace(entry, value=setup_data.get(entry.key, entry.value))
                for entry in _CREDENTIAL_ENTRIES
            ],
            step_id="user",
            errors=errors,
        )
        email = str(credentials[CONF_EMAIL])
        password = str(credentials[CONF_PASSWORD])
        try:
            profiles = await session.progress_until(
                fetch_profiles(session.mass, email, password, device_id),
                step_id="loading_profiles",
                text="loading_profiles",
                expires_in=60,
            )
        except ProfileLookupError as err:
            errors = {"base": err.reason}
            continue
        break

    previous_profile = str(setup_data.get(CONF_PROFILE_ID) or "")
    errors = None
    while True:
        selection = await session.form(
            _profile_entries(profiles, previous_profile),
            step_id="profile",
            errors=errors,
            last_step=True,
        )
        values: dict[str, ConfigValueType] = {
            CONF_EMAIL: email,
            CONF_PASSWORD: password,
            CONF_PROFILE_ID: str(selection[CONF_PROFILE_ID]),
            CONF_PROFILE_PIN: str(selection.get(CONF_PROFILE_PIN) or ""),
            CONF_DEVICE_ID: device_id,
        }
        if device_serial := setup_data.get(CONF_DEVICE_SERIAL):
            values[CONF_DEVICE_SERIAL] = device_serial
        try:
            await session.finish(values)
            return
        except SetupFlowError as err:
            errors = {"base": err.translation_key or str(err)}


async def fetch_profiles(
    mass: MusicAssistant, email: str, password: str, device_id: str
) -> list[dict[str, Any]]:
    """
    Fetch the profiles available on a 24six account.

    :param mass: MusicAssistant instance (for the HTTP session).
    :param email: Account email address.
    :param password: Account password.
    :param device_id: Device identifier for the API headers.
    """
    try:
        async with mass.http_session.post(
            f"{API_BASE_URL}/profile-list",
            headers=build_api_headers(device_id),
            json={"email": email, "password": password},
        ) as resp:
            if resp.status != 200:
                raise ProfileLookupError("login_failed")
            data: dict[str, Any] = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ProfileLookupError("connection_failed") from err

    profiles: list[dict[str, Any]] = [
        profile for profile in data.get("profiles") or [] if profile and profile.get("id")
    ]
    if not profiles:
        raise ProfileLookupError("no_profiles")
    return profiles


def _profile_entries(profiles: list[dict[str, Any]], previous_profile: str) -> list[ConfigEntry]:
    """
    Build the profile-selection form entries.

    :param profiles: The profiles as returned by the API.
    :param previous_profile: The profile id selected in an earlier setup, if any.
    """
    options = [
        ConfigValueOption(
            title=f"{profile.get('name', profile['id'])}"
            + (" (PIN required)" if profile.get("pin_required") else ""),
            value=str(profile["id"]),
        )
        for profile in profiles
    ]
    profile_ids = {str(option.value) for option in options}
    default_profile = previous_profile if previous_profile in profile_ids else str(options[0].value)
    return [
        ConfigEntry(
            key=CONF_PROFILE_ID,
            type=ConfigEntryType.STRING,
            required=True,
            options=options,
            default_value=default_profile,
            value=default_profile,
        ),
        ConfigEntry(
            key=CONF_PROFILE_PIN,
            type=ConfigEntryType.SECURE_STRING,
            required=False,
        ),
    ]
