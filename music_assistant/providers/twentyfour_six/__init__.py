"""24six music provider support for MusicAssistant."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import aiohttp
from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption, ConfigValueType
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from music_assistant_models.errors import LoginFailed

from .constants import (
    API_BASE_URL,
    CONF_ACTION_LOGIN,
    CONF_DEVICE_ID,
    CONF_DEVICE_SERIAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_PROFILE_PIN,
    CONF_PROFILES_DATA,
    CONF_SESSION_DATA,
    build_api_headers,
)
from .provider import TwentyFourSixProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType


SUPPORTED_FEATURES = {
    ProviderFeature.LIBRARY_ARTISTS,
    ProviderFeature.LIBRARY_ALBUMS,
    ProviderFeature.LIBRARY_TRACKS,
    ProviderFeature.LIBRARY_PLAYLISTS,
    ProviderFeature.LIBRARY_ARTISTS_EDIT,
    ProviderFeature.LIBRARY_ALBUMS_EDIT,
    ProviderFeature.LIBRARY_TRACKS_EDIT,
    ProviderFeature.LIBRARY_PLAYLISTS_EDIT,
    ProviderFeature.FAVORITE_ARTISTS_EDIT,
    ProviderFeature.FAVORITE_ALBUMS_EDIT,
    ProviderFeature.FAVORITE_TRACKS_EDIT,
    ProviderFeature.PLAYLIST_TRACKS_EDIT,
    ProviderFeature.PLAYLIST_CREATE,
    ProviderFeature.ARTIST_ALBUMS,
    ProviderFeature.ARTIST_TOPTRACKS,
    ProviderFeature.SEARCH,
    ProviderFeature.BROWSE,
    ProviderFeature.RECOMMENDATIONS,
}


async def _fetch_profiles_for_config(
    mass: MusicAssistant,
    email: str,
    password: str,
    device_id: str,
) -> list[dict[str, Any]]:
    """Fetch available profiles from the 24six API during config flow.

    :param mass: MusicAssistant instance (for HTTP session).
    :param email: Account email address.
    :param password: Account password (plaintext).
    :param device_id: Device identifier for API headers.
    """
    try:
        async with mass.http_session.post(
            f"{API_BASE_URL}/profile-list",
            headers=build_api_headers(device_id),
            json={"email": email, "password": password},
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                msg = f"Login failed (status {resp.status}): {text[:200]}"
                raise LoginFailed(msg)
            data: dict[str, Any] = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as err:
        msg = f"Unable to connect to 24six: {err}"
        raise LoginFailed(msg) from err

    profiles: list[dict[str, Any]] = data.get("profiles", [])
    if not profiles:
        msg = "No profiles found on this account"
        raise LoginFailed(msg)
    return profiles


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    return TwentyFourSixProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """Return Config entries to setup this provider.

    Uses a multi-step flow:
    1. User enters email and password, then clicks Login.
    2. Profiles are fetched and shown in a dropdown.
    3. PIN field is shown only if the selected profile requires one.
    """
    entries: list[ConfigEntry] = []

    # Step 1: Always show email and password
    entries.append(
        ConfigEntry(
            key=CONF_EMAIL,
            type=ConfigEntryType.STRING,
            label="Email Address",
            required=True,
            description="Your 24six account email address.",
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_PASSWORD,
            type=ConfigEntryType.SECURE_STRING,
            label="Password",
            required=True,
            description="Your 24six account password.",
        )
    )

    # Read stored profiles from previous config step (if any)
    profiles: list[dict[str, Any]] = []
    profiles_json = str(values.get(CONF_PROFILES_DATA, "")) if values else ""
    if profiles_json:
        try:
            profiles = json.loads(profiles_json)
        except (json.JSONDecodeError, TypeError):
            profiles = []

    has_credentials = bool(values and values.get(CONF_EMAIL) and values.get(CONF_PASSWORD))

    # Handle login action: fetch profiles from API
    if action == CONF_ACTION_LOGIN and has_credentials:
        assert values is not None
        email = str(values[CONF_EMAIL])
        # Config flow values dict stores encrypted form; decrypt explicitly.
        # At runtime, config.get_value() handles decryption transparently.
        password = mass.config.decrypt_string(str(values[CONF_PASSWORD]))
        raw_device_id = values.get(CONF_DEVICE_ID)
        device_id = str(raw_device_id) if raw_device_id else str(uuid.uuid4())
        profiles = await _fetch_profiles_for_config(mass, email, password, device_id)
        profiles_json = json.dumps(profiles)
        if not values.get(CONF_DEVICE_ID):
            values[CONF_DEVICE_ID] = device_id

    # Login button: shown when no profiles are loaded yet
    entries.append(
        ConfigEntry(
            key=CONF_ACTION_LOGIN,
            type=ConfigEntryType.ACTION,
            label="Login",
            description="Login with your credentials to load available profiles.",
            action=CONF_ACTION_LOGIN,
            action_label="Login",
            hidden=bool(profiles),
        )
    )

    # Hidden field: store fetched profiles data across config steps
    entries.append(
        ConfigEntry(
            key=CONF_PROFILES_DATA,
            type=ConfigEntryType.STRING,
            label="Profiles data",
            hidden=True,
            required=False,
            value=profiles_json or None,
            default_value="",
        )
    )

    # Step 2: Profile dropdown (only after profiles are loaded)
    if profiles:
        selected_id = str(values.get(CONF_PROFILE_ID, "")) if values else ""
        if not selected_id:
            selected_id = str(profiles[0]["id"])

        entries.append(
            ConfigEntry(
                key=CONF_PROFILE_ID,
                type=ConfigEntryType.STRING,
                label="Profile",
                required=True,
                description="Select the profile to use.",
                options=[
                    ConfigValueOption(
                        title=(
                            f"{p['name']} (PIN required)" if p.get("pin_required") else p["name"]
                        ),
                        value=str(p["id"]),
                    )
                    for p in profiles
                ],
                default_value=str(profiles[0]["id"]),
                value=selected_id,
            )
        )

        # PIN field: always shown (not required) since visibility can't
        # react to dropdown changes. Profiles needing a PIN are labeled
        # "(PIN required)" in the dropdown to guide the user.
        entries.append(
            ConfigEntry(
                key=CONF_PROFILE_PIN,
                type=ConfigEntryType.SECURE_STRING,
                label="Profile PIN",
                required=False,
                description="4-digit PIN, only needed if your selected profile requires one.",
            )
        )

    # Hidden fields for session persistence
    entries.append(
        ConfigEntry(
            key=CONF_SESSION_DATA,
            type=ConfigEntryType.SECURE_STRING,
            label="Session data",
            hidden=True,
            required=False,
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_DEVICE_ID,
            type=ConfigEntryType.STRING,
            label="Device ID",
            hidden=True,
            required=False,
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_DEVICE_SERIAL,
            type=ConfigEntryType.STRING,
            label="Device Serial",
            hidden=True,
            required=False,
        )
    )

    return tuple(entries)
