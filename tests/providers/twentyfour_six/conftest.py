"""Shared fixtures for the 24six provider tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from music_assistant.providers.twentyfour_six import SUPPORTED_FEATURES
from music_assistant.providers.twentyfour_six.provider import TwentyFourSixProvider


def _create_task(coro: Coroutine[Any, Any, Any], **_kwargs: Any) -> asyncio.Task[Any]:
    """Run a coroutine as a real task, as the cache decorator expects from mass.create_task."""
    return asyncio.create_task(coro)


@pytest.fixture
def provider() -> TwentyFourSixProvider:
    """Create a real TwentyFourSixProvider with mocked dependencies and a cold cache."""
    mass = Mock()
    mass.create_task = _create_task
    mass.cache.get_with_freshness = AsyncMock(return_value=(None, False, False))
    mass.cache.get = AsyncMock(return_value=None)
    mass.cache.set = AsyncMock()
    mass.cache.delete = AsyncMock()
    manifest = Mock()
    manifest.domain = "twentyfour_six"
    config = Mock()
    config.instance_id = "twentyfour_six--test"
    config.name = "24six Test"
    config.enabled = True
    config.get_value.side_effect = lambda key, default=None: {"log_level": "GLOBAL"}.get(
        key, default
    )
    instance = TwentyFourSixProvider(mass, manifest, config, SUPPORTED_FEATURES)
    instance.api.api_get = AsyncMock(return_value={})  # type: ignore[method-assign]
    instance.api.api_post = AsyncMock(return_value={})  # type: ignore[method-assign]
    instance.api.api_delete = AsyncMock(return_value={})  # type: ignore[method-assign]
    instance.api.api_patch = AsyncMock(return_value={})  # type: ignore[method-assign]
    instance.api.api_get_stream_url = AsyncMock(  # type: ignore[method-assign]
        return_value="https://cdn.example.com/track.m4a"
    )
    instance.api.log_playback = AsyncMock()  # type: ignore[method-assign]
    return instance
