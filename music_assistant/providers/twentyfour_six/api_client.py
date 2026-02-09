"""API Client for 24six using the v3 mobile API with Bearer token auth."""

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
    ResourceTemporarilyUnavailable,
)

from music_assistant.helpers.throttle_retry import ThrottlerManager, throttle_with_retries

from .constants import (
    API_BASE_URL,
    CONF_DEVICE_ID,
    CONF_DEVICE_SERIAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_PROFILE_PIN,
    CONF_SESSION_DATA,
    build_api_headers,
)

if TYPE_CHECKING:
    from .provider import TwentyFourSixProvider


_MAX_ERROR_LOG = 500


class TwentyFourSixAPIClient:
    """HTTP client for 24six using the v3 mobile API with Bearer token auth."""

    throttler = ThrottlerManager(rate_limit=1, period=1)

    def __init__(self, provider: TwentyFourSixProvider) -> None:
        """Initialize the API client."""
        self.provider = provider
        self.logger = provider.logger
        self.mass = provider.mass
        self._access_token: str = ""
        self._device_id: str = ""
        self._device_serial: str = ""
        self._auth_lock = asyncio.Lock()

    @property
    def device_id(self) -> str:
        """Return the device_id, generating a temporary one if needed.

        The authoritative device_id is assigned by the server during login
        and persisted in the session data. This property generates a temporary
        UUID only so the login request itself has a value for X-DEVICE-ID.
        """
        if not self._device_id:
            stored = self.provider.config.get_value(CONF_DEVICE_ID)
            if stored:
                self._device_id = str(stored)
            else:
                self._device_id = str(uuid.uuid4())
        return self._device_id

    @property
    def device_serial(self) -> str:
        """Return the device_serial, generating one if needed."""
        if not self._device_serial:
            stored = self.provider.config.get_value(CONF_DEVICE_SERIAL)
            if stored:
                self._device_serial = str(stored)
            else:
                self._device_serial = str(uuid.uuid4()).upper()
                self.provider.update_device_serial(self._device_serial)
        return self._device_serial

    async def login(self) -> None:
        """Perform login via the v3 mobile API.

        Uses the profile ID selected during config flow.
        """
        email = self.provider.config.get_value(CONF_EMAIL)
        password = self.provider.config.get_value(CONF_PASSWORD)
        profile_id = self.provider.config.get_value(CONF_PROFILE_ID)
        if not email or not password or not profile_id:
            msg = "Email, password, and profile are required"
            raise LoginFailed(msg)

        payload: dict[str, Any] = {
            "email": str(email),
            "password": str(password),
            "profile_id": str(profile_id),
        }

        pin_value = self.provider.config.get_value(CONF_PROFILE_PIN)
        if pin_value:
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
                    msg = f"Login failed with status {resp.status}"
                    raise LoginFailed(msg)
                data: dict[str, Any] = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            msg = f"Login request failed: {err}"
            raise LoginFailed(msg) from err

        token = data.get("token")
        if not token:
            msg = "No access token in login response"
            raise LoginFailed(msg)

        self._access_token = str(token)
        if server_device_id := data.get("device_id"):
            self._device_id = str(server_device_id)
            self.provider.update_device_id(self._device_id)
        profile_data = data.get("profile", {})
        self.logger.info(
            "Logged in as profile '%s' (id=%s)",
            profile_data.get("name", "unknown"),
            profile_data.get("id", "unknown"),
        )
        await self._register_device()

    async def _register_device(self) -> None:
        """Register the device with the server."""
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

    async def _raw_request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
    ) -> int:
        """Make an unauthenticated, unthrottled HTTP request and return the status code.

        Uses the current token/device state for headers but does not check
        or refresh auth. Used by ensure_logged_in (token probe) to avoid
        re-entering the auth lock through _handle_api_response.

        :param method: HTTP method.
        :param endpoint: API endpoint path.
        :param params: Optional query parameters.
        """
        url = f"{API_BASE_URL}/{endpoint.lstrip('/')}"
        headers = build_api_headers(self.device_id, self._access_token, self.device_serial)
        async with self.mass.http_session.request(
            method, url, headers=headers, params=params
        ) as resp:
            status: int = resp.status
            return status

    async def ensure_logged_in(self) -> None:
        """Ensure we have a valid token, re-authenticating if needed."""
        async with self._auth_lock:
            if self._access_token:
                return
            session_data = self.provider.config.get_value(CONF_SESSION_DATA)
            if session_data:
                try:
                    data = json.loads(str(session_data))
                    token = data.get("token")
                    saved_device_id = data.get("device_id")
                    if token and saved_device_id:
                        self._access_token = str(token)
                        self._device_id = str(saved_device_id)
                        try:
                            status = await self._raw_request(
                                "GET",
                                "music/artist",
                                params={"page": "1", "per_page": "1"},
                            )
                            if status == 401:
                                self._access_token = ""
                                self._device_id = ""
                            else:
                                # 5xx or success: assume token is valid.
                                # The first real API call will handle 401
                                # if the token is actually expired.
                                return
                        except (aiohttp.ClientError, TimeoutError):
                            # Network error doesn't invalidate the token.
                            # Keep it and let the first real request retry.
                            return
                except json.JSONDecodeError:
                    self.logger.debug("Ignoring corrupted session data")
            await self.login()
            self._persist_session()

    def _persist_session(self) -> None:
        """Persist the access token and server device_id for cross-restart survival."""
        data = {"token": self._access_token, "device_id": self._device_id}
        self.provider.update_session_data(json.dumps(data))

    async def _handle_token_expired(self, failed_token: str) -> None:
        """Handle 401 by re-authenticating with a lock to prevent concurrent logins.

        :param failed_token: The token that received the 401 response.
        """
        async with self._auth_lock:
            if self._access_token != failed_token:
                # Another coroutine already refreshed the token while we waited.
                return
            self._access_token = ""
            await self.login()
            self._persist_session()

    @throttle_with_retries  # type: ignore[type-var]
    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated, throttled request to the v3 API.

        :param method: HTTP method (GET, POST, DELETE, PATCH).
        :param endpoint: API endpoint path (leading slash stripped).
        :param params: Optional query parameters (dict or list of tuples for repeated keys).
        :param json_data: Optional JSON body for POST requests.
        """
        if not self._access_token:
            await self.ensure_logged_in()
        token = self._access_token
        url = f"{API_BASE_URL}/{endpoint.lstrip('/')}"
        headers = build_api_headers(self.device_id, token, self.device_serial)
        try:
            async with self.mass.http_session.request(
                method, url, headers=headers, params=params, json=json_data
            ) as resp:
                return await self._handle_api_response(resp, endpoint, token)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ResourceTemporarilyUnavailable(str(err), backoff_time=5) from err

    async def api_get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request to the v3 API."""
        return await self._request("GET", endpoint, params=params)

    async def api_post(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
        *,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Make a POST request to the v3 API."""
        return await self._request("POST", endpoint, params=params, json_data=data)

    async def api_delete(
        self,
        endpoint: str,
    ) -> dict[str, Any]:
        """Make a DELETE request to the v3 API."""
        return await self._request("DELETE", endpoint)

    async def api_patch(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Make a PATCH request to the v3 API."""
        return await self._request("PATCH", endpoint, params=params)

    @throttle_with_retries  # type: ignore[type-var]
    async def api_get_stream_url(
        self,
        item_id: str,
        audio_format: str = "m4a",
    ) -> str:
        """Get the streaming URL for a track (follows 302 redirect)."""
        if not self._access_token:
            await self.ensure_logged_in()
        token = self._access_token
        endpoint = f"content/{item_id}/play"
        url = f"{API_BASE_URL}/{endpoint}"
        headers = build_api_headers(self.device_id, token, self.device_serial)
        try:
            async with self.mass.http_session.get(
                url,
                headers=headers,
                params={"format": audio_format},
                allow_redirects=False,
            ) as resp:
                if resp.status == 302:
                    location: str = resp.headers.get("Location", "")
                    if location:
                        return location
                    msg = f"No redirect URL for track {item_id}"
                    raise MediaNotFoundError(msg)
                await self._handle_api_response(resp, endpoint, token)
                msg = f"Expected 302 redirect for stream URL, got {resp.status}"
                raise MediaNotFoundError(msg)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ResourceTemporarilyUnavailable(str(err), backoff_time=5) from err

    async def _handle_api_response(
        self, response: aiohttp.ClientResponse, endpoint: str, request_token: str = ""
    ) -> dict[str, Any]:
        """Handle v3 API response with error handling.

        :param response: The aiohttp response.
        :param endpoint: The API endpoint (for error messages).
        :param request_token: The token used for this request, passed to
            _handle_token_expired to avoid a race where self._access_token
            is read after another coroutine has already refreshed it.
        """
        if response.status == 401:
            self.logger.debug("Token expired, re-authenticating")
            await self._handle_token_expired(request_token or self._access_token)
            raise ResourceTemporarilyUnavailable("Token expired, re-authenticated", backoff_time=1)
        if response.status == 404:
            msg = f"{endpoint} not found"
            raise MediaNotFoundError(msg)
        if response.status == 429:
            backoff = int(response.headers.get("Retry-After", "30"))
            raise ResourceTemporarilyUnavailable("Rate limited", backoff_time=backoff)
        if response.status in (502, 503):
            raise ResourceTemporarilyUnavailable(backoff_time=30)
        if response.status >= 400:
            text = await response.text()
            self.logger.warning("API error %s on %s", response.status, endpoint)
            self.logger.debug("API error body: %s", text[:_MAX_ERROR_LOG])
            raise ResourceTemporarilyUnavailable(f"API error {response.status}")
        if response.status == 204:
            return {}
        try:
            result: dict[str, Any] = await response.json()
        except (json.JSONDecodeError, aiohttp.ContentTypeError) as err:
            raise ResourceTemporarilyUnavailable(
                f"Failed to parse response from {endpoint}"
            ) from err
        return result

    async def log_playback(
        self,
        item_id: str,
        seconds: int,
        current: int,
    ) -> None:
        """Report playback progress for a track (fire-and-forget).

        :param item_id: The content/track ID.
        :param seconds: Total seconds listened.
        :param current: Current playback position in seconds.
        """
        with contextlib.suppress(LoginFailed, MediaNotFoundError, ResourceTemporarilyUnavailable):
            await self._request(
                "POST",
                f"content/{item_id}/log",
                params={
                    "current": str(current),
                    "device_id": self.device_id,
                    "is_offline": "0",
                    "seconds": str(seconds),
                },
            )

    async def close(self) -> None:
        """Clean up resources (no-op, uses shared HTTP session)."""
