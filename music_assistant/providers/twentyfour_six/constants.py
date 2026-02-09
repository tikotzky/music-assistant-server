"""Constants for the 24six music provider."""

from typing import Final

# Base URL for v3 mobile API
API_BASE_URL: Final[str] = "https://24six.app/api/v3"

# Mobile API platform key (iOS app)
API_PLATFORM_KEY: Final[str] = "production-ios-d8225f34"

# App version headers (mimic iOS app)
API_MINOR_VERSION: Final[str] = "11"
API_APP_VERSION: Final[str] = "2.3.8"
API_OS_VERSION: Final[str] = "26.1"
API_USER_AGENT: Final[str] = "24Six/2.3.8 (app.tfs.prod; build:162; iOS 26.1.0) Alamofire/5.7.1"

# Config keys
CONF_EMAIL: Final[str] = "twentyfour_six_email"
CONF_PASSWORD: Final[str] = "twentyfour_six_password"
CONF_PROFILE_ID: Final[str] = "twentyfour_six_profile_id"
CONF_PROFILE_PIN: Final[str] = "twentyfour_six_profile_pin"
CONF_PROFILES_DATA: Final[str] = "twentyfour_six_profiles_data"
CONF_SESSION_DATA: Final[str] = "twentyfour_six_session_data"
CONF_DEVICE_ID: Final[str] = "twentyfour_six_device_id"
CONF_DEVICE_SERIAL: Final[str] = "twentyfour_six_device_serial"

# Config action keys
CONF_ACTION_LOGIN: Final[str] = "twentyfour_six_action_login"

# Maximum pages to fetch (safety limit)
MAX_PAGES: Final[int] = 100


def build_api_headers(
    device_id: str,
    access_token: str | None = None,
    device_serial: str = "",
) -> dict[str, str]:
    """Build standard headers for v3 API requests.

    :param device_id: Device identifier for API headers.
    :param access_token: Optional Bearer token for authenticated requests.
    :param device_serial: Device serial identifier for API headers.
    """
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Platform-Key": API_PLATFORM_KEY,
        "X-API-MINOR-VERSION": API_MINOR_VERSION,
        "app-version": API_APP_VERSION,
        "os": "iOS",
        "os-version": API_OS_VERSION,
        "User-Agent": API_USER_AGENT,
        "X-DEVICE-ID": device_id,
    }
    if device_serial:
        headers["X-DEVICE-SERIAL"] = device_serial
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers
