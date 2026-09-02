"""API client for 24six using the v3 mobile API with Bearer token auth."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import TYPE_CHECKING, Any

import aiohttp
from music_assistant_models.errors import (
    LoginFailed,
    MediaNotFoundError,
    MusicAssistantError,
    ResourceTemporarilyUnavailable,
)

from music_assistant.helpers.datetime import utc
from music_assistant.helpers.throttle_retry import (
    ThrottlerManager,
    parse_retry_after,
    throttle_with_retries,
)

from .constants import (
    API_BASE_URL,
    CONF_DEVICE_ID,
    CONF_DEVICE_SERIAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_PROFILE_PIN,
    CONF_SESSION_DATA,
    STREAMED_AT_FORMAT,
)
from .helpers import build_api_headers, error_message

if TYPE_CHECKING:
    from collections.abc import Callable

    from .provider import TwentyFourSixProvider

type ParamsType = dict[str, Any] | list[tuple[str, str]] | None

_MAX_ERROR_LOG = 500
# authenticated endpoint used to probe whether a restored token is still valid; it also
# returns the profile details (content permissions) that a fresh login would provide
_PROFILE_ENDPOINT = "profile"
_TRANSLATION_OWNER = "provider.twentyfour_six"


class TwentyFourSixAPIClient:
    """HTTP client for 24six using the v3 mobile API with Bearer token auth."""

    throttler = ThrottlerManager(rate_limit=1, period=1)

    def __init__(
        self,
        provider: TwentyFourSixProvider,
        persist_setup_value: Callable[[str, str], None],
    ) -> None:
        """
        Initialize the API client.

        :param provider: The provider instance owning this client (for config and logging).
        :param persist_setup_value: Callback that persists a rotated setup value
            (session token, device ids) to the provider's setup data.
        """
        self.provider = provider
        self.logger = provider.logger
        self.mass = provider.mass
        # profile details as returned by the login or the session restore
        self.profile: dict[str, Any] = {}
        self._persist_setup_value = persist_setup_value
        self._access_token: str = ""
        self._device_id: str = ""
        self._device_serial: str = ""
        self._auth_lock = asyncio.Lock()

    @property
    def device_id(self) -> str:
        """Return the device id that identifies this Music Assistant instance to the API."""
        if not self._device_id:
            # the server assigns the authoritative id at login and it is persisted with
            # the session; until then a random one lets the login request carry a header
            stored = self.provider.get_setup_value(CONF_DEVICE_ID)
            self._device_id = str(stored) if stored else str(uuid.uuid4())
        return self._device_id

    @property
    def device_serial(self) -> str:
        """Return the device serial, generating and persisting one if needed."""
        if not self._device_serial:
            stored = self.provider.get_setup_value(CONF_DEVICE_SERIAL)
            if stored:
                self._device_serial = str(stored)
            else:
                self._device_serial = str(uuid.uuid4()).upper()
                self._persist_setup_value(CONF_DEVICE_SERIAL, self._device_serial)
        return self._device_serial

    def profile_allows(self, content_type: str) -> bool:
        """
        Return whether the logged-in profile may access the given content type.

        An unknown permission (no profile details yet) counts as allowed.

        :param content_type: The content type key of the profile's allowed map.
        """
        allowed = self.profile.get("allowed")
        if not isinstance(allowed, dict) or content_type not in allowed:
            return True
        return bool(allowed[content_type])

    async def login(self) -> None:
        """Perform a login via the v3 mobile API using the profile selected during setup."""
        email = self.provider.get_setup_value(CONF_EMAIL)
        password = self.provider.get_setup_value(CONF_PASSWORD)
        profile_id = self.provider.get_setup_value(CONF_PROFILE_ID)
        if not email or not password or not profile_id:
            raise LoginFailed(
                "Email, password, and profile are required",
                translation_key="login_failed",
                translation_owner=_TRANSLATION_OWNER,
            )

        payload: dict[str, Any] = {
            "email": str(email),
            "password": str(password),
            "profile_id": str(profile_id),
        }
        if pin_value := self.provider.get_setup_value(CONF_PROFILE_PIN):
            payload["pin"] = str(pin_value)

        self.logger.debug("Logging in with profile_id=%s", profile_id)
        try:
            async with self.mass.http_session.post(
                f"{API_BASE_URL}/login",
                headers=build_api_headers(self.device_id, device_serial=self.device_serial),
                json=payload,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    self.logger.debug(
                        "Login failed: status=%s body=%s", resp.status, text[:_MAX_ERROR_LOG]
                    )
                    message = error_message(text)
                    raise LoginFailed(
                        f"Login failed with status {resp.status}: {message}",
                        translation_key="pin_required"
                        if "pin" in message.lower()
                        else "login_failed",
                        translation_owner=_TRANSLATION_OWNER,
                    )
                data: dict[str, Any] = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LoginFailed(
                f"Login request failed: {err}",
                translation_key="connection_failed",
                translation_owner=_TRANSLATION_OWNER,
            ) from err

        token = data.get("token")
        if not token:
            raise LoginFailed(
                "No access token in login response",
                translation_key="login_failed",
                translation_owner=_TRANSLATION_OWNER,
            )

        self._access_token = str(token)
        if server_device_id := data.get("device_id"):
            self._device_id = str(server_device_id)
            self._persist_setup_value(CONF_DEVICE_ID, self._device_id)
        self.profile = data.get("profile") or {}
        self.logger.info(
            "Logged in as profile '%s' (id=%s)",
            self.profile.get("name", "unknown"),
            self.profile.get("id", "unknown"),
        )
        self.logger.debug("Profile content access: %s", self.profile.get("allowed"))
        await self._register_device()

    async def logout(self) -> None:
        """Invalidate the current session on the server (best effort)."""
        if not self._access_token:
            return
        try:
            await self._raw_request("POST", "logout")
        except (aiohttp.ClientError, TimeoutError) as err:
            self.logger.debug("Logout request failed: %s", err)
        self._access_token = ""
        self.profile = {}

    async def ensure_logged_in(self) -> None:
        """Ensure we have a valid token, restoring the persisted session or logging in."""
        async with self._auth_lock:
            if self._access_token:
                return
            if await self._restore_session():
                return
            await self.login()
            self._persist_session()

    async def api_get(self, endpoint: str, *, params: ParamsType = None) -> dict[str, Any]:
        """
        Make a GET request to the v3 API.

        :param endpoint: API endpoint path relative to the API base URL.
        :param params: Optional query parameters.
        """
        return await self._request("GET", endpoint, params=params)

    async def api_post(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
        *,
        params: ParamsType = None,
    ) -> dict[str, Any]:
        """
        Make a POST request to the v3 API.

        :param endpoint: API endpoint path relative to the API base URL.
        :param data: Optional JSON body.
        :param params: Optional query parameters.
        """
        return await self._request("POST", endpoint, params=params, json_data=data)

    async def api_delete(self, endpoint: str) -> dict[str, Any]:
        """
        Make a DELETE request to the v3 API.

        :param endpoint: API endpoint path relative to the API base URL.
        """
        return await self._request("DELETE", endpoint)

    async def api_patch(self, endpoint: str, *, params: ParamsType = None) -> dict[str, Any]:
        """
        Make a PATCH request to the v3 API.

        :param endpoint: API endpoint path relative to the API base URL.
        :param params: Optional query parameters.
        """
        return await self._request("PATCH", endpoint, params=params)

    @throttle_with_retries
    async def api_get_stream_url(self, endpoint: str, params: dict[str, str]) -> str:
        """
        Resolve the stream URL behind a play endpoint (the API answers with a redirect).

        :param endpoint: The play endpoint, e.g. ``content/123/play``.
        :param params: Query parameters such as the requested format.
        """
        url, headers, token = await self._prepare_request(endpoint)
        try:
            async with self.mass.http_session.get(
                url, headers=headers, params=params, allow_redirects=False
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    if location := resp.headers.get("Location", ""):
                        return location
                    raise MediaNotFoundError(f"No redirect URL for {endpoint}")
                await self._handle_api_response(resp, endpoint, token)
                raise MediaNotFoundError(f"Expected a redirect for {endpoint}, got {resp.status}")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ResourceTemporarilyUnavailable(str(err), backoff_time=5) from err

    async def log_playback(self, item_id: str, seconds: int, current: int) -> None:
        """
        Report a finished play of a content item, the way the app does.

        :param item_id: The content (track or episode) id.
        :param seconds: Seconds listened during the play.
        :param current: Playback position in seconds where the play ended.
        """
        try:
            await self._request(
                "POST",
                f"content/{item_id}/log",
                params={
                    "current": str(current),
                    "device_id": self.device_id,
                    "is_offline": "0",
                    "seconds": str(seconds),
                    "streamed_at": utc().strftime(STREAMED_AT_FORMAT),
                },
            )
        except MusicAssistantError as err:
            # a lost play log must not disturb playback, but it should not go unnoticed
            self.logger.warning("Could not log the play of %s: %s", item_id, err)

    async def _register_device(self) -> None:
        """Register this device with the server so playback logging is accepted."""
        try:
            async with self.mass.http_session.post(
                f"{API_BASE_URL}/device",
                headers=build_api_headers(self.device_id, self._access_token, self.device_serial),
                json={"device_name": "Music Assistant", "device_id": self.device_id},
            ) as resp:
                if resp.status == 200:
                    self.logger.debug("Device registered successfully")
                else:
                    self.logger.debug("Device registration returned status %s", resp.status)
        except (aiohttp.ClientError, TimeoutError) as err:
            self.logger.debug("Device registration failed: %s", err)

    async def _restore_session(self) -> bool:
        """Restore the persisted token and device id, returning True when usable."""
        session_data = self.provider.get_setup_value(CONF_SESSION_DATA)
        if not session_data:
            return False
        try:
            data = json.loads(str(session_data))
        except json.JSONDecodeError:
            self.logger.debug("Ignoring corrupted session data")
            return False
        token = data.get("token")
        saved_device_id = data.get("device_id")
        if not token or not saved_device_id:
            return False
        self._access_token = str(token)
        self._device_id = str(saved_device_id)
        try:
            status, profile_data = await self._raw_request("GET", _PROFILE_ENDPOINT)
        except aiohttp.ClientError, TimeoutError:
            # a network error does not invalidate the token: keep it and let the
            # first real request retry
            return True
        if status == 401:
            self._access_token = ""
            self._device_id = ""
            return False
        if status == 200 and isinstance(profile_data, dict):
            self.profile = profile_data.get("profile") or profile_data
            self.logger.debug(
                "Restored session for profile '%s', content access: %s",
                self.profile.get("name", "unknown"),
                self.profile.get("allowed"),
            )
        # 5xx or success: assume the token is valid, the first real API call
        # handles a 401 if it turns out to be expired after all
        return True

    async def _raw_request(
        self, method: str, endpoint: str, *, params: ParamsType = None
    ) -> tuple[int, Any]:
        """
        Make an unthrottled request without auth handling.

        Returns the status code and the decoded JSON body (None when there is none).

        :param method: HTTP method.
        :param endpoint: API endpoint path relative to the API base URL.
        :param params: Optional query parameters.
        """
        url = f"{API_BASE_URL}/{endpoint.lstrip('/')}"
        headers = build_api_headers(self.device_id, self._access_token, self.device_serial)
        async with self.mass.http_session.request(
            method, url, headers=headers, params=params
        ) as resp:
            status: int = resp.status
            body: Any = None
            with contextlib.suppress(json.JSONDecodeError, aiohttp.ContentTypeError):
                body = await resp.json()
            return status, body

    def _persist_session(self) -> None:
        """Persist the access token and server device_id so they survive a restart."""
        data = {"token": self._access_token, "device_id": self._device_id}
        self._persist_setup_value(CONF_SESSION_DATA, json.dumps(data))

    async def _handle_token_expired(self, failed_token: str) -> None:
        """
        Handle a 401 by re-authenticating, serialized so concurrent 401s login once.

        :param failed_token: The token that received the 401 response.
        """
        async with self._auth_lock:
            if self._access_token != failed_token:
                # another coroutine already refreshed the token while we waited
                return
            self._access_token = ""
            await self.login()
            self._persist_session()

    async def _prepare_request(self, endpoint: str) -> tuple[str, dict[str, str], str]:
        """
        Return the URL, headers and token for an authenticated request.

        :param endpoint: API endpoint path relative to the API base URL.
        """
        if not self._access_token:
            await self.ensure_logged_in()
        token = self._access_token
        url = f"{API_BASE_URL}/{endpoint.lstrip('/')}"
        return url, build_api_headers(self.device_id, token, self.device_serial), token

    @throttle_with_retries
    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: ParamsType = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make an authenticated, throttled request to the v3 API.

        :param method: HTTP method (GET, POST, DELETE, PATCH).
        :param endpoint: API endpoint path relative to the API base URL.
        :param params: Optional query parameters (dict or list of tuples for repeated keys).
        :param json_data: Optional JSON body.
        """
        url, headers, token = await self._prepare_request(endpoint)
        try:
            async with self.mass.http_session.request(
                method, url, headers=headers, params=params, json=json_data
            ) as resp:
                return await self._handle_api_response(resp, endpoint, token)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ResourceTemporarilyUnavailable(str(err), backoff_time=5) from err

    async def _handle_api_response(
        self, response: aiohttp.ClientResponse, endpoint: str, request_token: str = ""
    ) -> dict[str, Any]:
        """
        Turn a v3 API response into its JSON body, mapping HTTP errors to MA errors.

        :param response: The aiohttp response.
        :param endpoint: The API endpoint (for error messages).
        :param request_token: The token used for this request, so a 401 only triggers a
            re-login when nobody refreshed the token in the meantime.
        """
        if response.status == 401:
            self.logger.debug("Token expired, re-authenticating")
            await self._handle_token_expired(request_token or self._access_token)
            raise ResourceTemporarilyUnavailable("Token expired, re-authenticated", backoff_time=1)
        if response.status == 404:
            raise MediaNotFoundError(f"{endpoint} not found")
        if response.status == 429:
            backoff = parse_retry_after(response.headers.get("Retry-After")) or 30
            raise ResourceTemporarilyUnavailable("Rate limited", backoff_time=backoff)
        if response.status in (502, 503):
            raise ResourceTemporarilyUnavailable(backoff_time=30)
        if response.status >= 400:
            text = await response.text()
            self.logger.warning("API error %s on %s", response.status, endpoint)
            self.logger.debug("API error body: %s", text[:_MAX_ERROR_LOG])
            if response.status >= 500:
                raise ResourceTemporarilyUnavailable(f"API error {response.status}")
            # a client error (validation, method not allowed, ...) will not get better
            # by retrying, so fail right away with the server's own message
            raise MusicAssistantError(
                f"API error {response.status} on {endpoint}: {error_message(text)}"
            )
        if response.status == 204:
            return {}
        try:
            result = await response.json()
        except (json.JSONDecodeError, aiohttp.ContentTypeError) as err:
            raise ResourceTemporarilyUnavailable(
                f"Failed to parse response from {endpoint}"
            ) from err
        if isinstance(result, list):
            # some endpoints answer with a bare list, normalize to the usual data key
            return {"data": result}
        if not isinstance(result, dict):
            raise ResourceTemporarilyUnavailable(f"Unexpected response from {endpoint}")
        return result
