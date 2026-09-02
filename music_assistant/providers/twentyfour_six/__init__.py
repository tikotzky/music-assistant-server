"""24six music provider support for Music Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from music_assistant_models.enums import ProviderFeature

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
    ProviderFeature.LIBRARY_PODCASTS,
    ProviderFeature.LIBRARY_ALBUMS_EDIT,
    ProviderFeature.LIBRARY_TRACKS_EDIT,
    ProviderFeature.LIBRARY_PLAYLISTS_EDIT,
    ProviderFeature.LIBRARY_PODCASTS_EDIT,
    ProviderFeature.FAVORITE_ARTISTS_EDIT,
    ProviderFeature.FAVORITE_ALBUMS_EDIT,
    ProviderFeature.FAVORITE_TRACKS_EDIT,
    ProviderFeature.FAVORITE_PODCASTS_EDIT,
    ProviderFeature.PLAYLIST_TRACKS_EDIT,
    ProviderFeature.PLAYLIST_CREATE_TRACKS,
    ProviderFeature.ARTIST_ALBUMS,
    ProviderFeature.ARTIST_TRACKS,
    ProviderFeature.ARTIST_TOPTRACKS,
    ProviderFeature.ARTIST_TOPALBUMS,
    ProviderFeature.SIMILAR_TRACKS,
    ProviderFeature.SIMILAR_ARTISTS,
    ProviderFeature.SEARCH,
    ProviderFeature.BROWSE,
    ProviderFeature.RECOMMENDATIONS,
}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize the provider (instance) with the given configuration."""
    return TwentyFourSixProvider(mass, manifest, config, SUPPORTED_FEATURES)
