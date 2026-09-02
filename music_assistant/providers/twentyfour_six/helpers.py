"""Helpers for the 24six music provider."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from music_assistant.helpers.util import try_parse_int

from .constants import (
    API_APP_VERSION,
    API_MINOR_VERSION,
    API_OS_VERSION,
    API_PLATFORM_KEY,
    API_USER_AGENT,
)


def build_api_headers(
    device_id: str,
    access_token: str | None = None,
    device_serial: str = "",
) -> dict[str, str]:
    """
    Build the standard headers for v3 API requests.

    :param device_id: Device identifier for the X-DEVICE-ID header.
    :param access_token: Optional Bearer token for authenticated requests.
    :param device_serial: Device serial identifier for the X-DEVICE-SERIAL header.
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


def valid_items(items: Any, key: str = "id") -> list[dict[str, Any]]:
    """
    Return the dict items of an API list that carry the given key.

    :param items: The raw list from an API response (anything else yields no items).
    :param key: The key every usable item must carry.
    """
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get(key)]


def total_pages(pagination: Any) -> int | None:
    """
    Return the total number of pages from a pagination object, if known.

    :param pagination: The pagination object of a listing or playlist response.
    """
    if not isinstance(pagination, dict):
        return None
    for key in ("total_pages", "last_page"):
        if (pages := try_parse_int(pagination.get(key), None)) is not None:
            return pages
    # the API reports totals and a page size rather than a page count
    total = try_parse_int(pagination.get("total"), None)
    per_page = try_parse_int(pagination.get("per_page"), None)
    if total is None or not per_page:
        return None
    return -(-total // per_page)


def page_size(pagination: Any) -> int | None:
    """
    Return the page size from a pagination object, if known.

    :param pagination: The pagination object of a listing or playlist response.
    """
    if not isinstance(pagination, dict):
        return None
    return try_parse_int(pagination.get("per_page"), None)


def has_next_page(pagination: dict[str, Any], page: int, item_count: int) -> bool:
    """
    Return whether a listing has another page after the given one.

    :param pagination: The pagination object from the response metadata.
    :param page: The page that was just fetched.
    :param item_count: The number of items on that page.
    """
    if "next_page" in pagination:
        return bool(pagination["next_page"])
    if (pages := total_pages(pagination)) is not None:
        return page < pages
    if (size := page_size(pagination)) is not None:
        return item_count >= size
    return False


def radio_stations(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return the radio stations of a live dashboard payload.

    :param dashboard: The raw ``live/dashboard`` response.
    """
    audio = dashboard.get("audio") or {}
    return valid_items(audio.get("radio") or dashboard.get("radio"))


def error_message(body: str) -> str:
    """
    Return the human readable message of an API error body, or the trimmed raw body.

    :param body: The raw response body of a failed request.
    """
    with suppress(json.JSONDecodeError, AttributeError, TypeError):
        parsed = json.loads(body)
        if isinstance(parsed, dict) and parsed.get("message"):
            return str(parsed["message"])
    return body[:200]
