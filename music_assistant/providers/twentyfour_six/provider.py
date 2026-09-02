"""24six music provider implementation."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from music_assistant_models.enums import ContentType, MediaType, StreamType
from music_assistant_models.errors import (
    LoginFailed,
    MediaNotFoundError,
    ResourceTemporarilyUnavailable,
    UnsupportedFeaturedException,
)
from music_assistant_models.media_items import (
    Album,
    Artist,
    AudioFormat,
    BrowseFolder,
    ItemMapping,
    MediaItemType,
    Playlist,
    Podcast,
    PodcastEpisode,
    Radio,
    RecommendationFolder,
    SearchResults,
    Track,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails, StreamMetadata

from music_assistant.controllers.cache import use_cache
from music_assistant.helpers.podcast_parsers import rank_episodes_by_date
from music_assistant.models.music_provider import MusicProvider

from .api_client import TwentyFourSixAPIClient
from .constants import (
    CONF_DEVICE_ID,
    CONF_DEVICE_SERIAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONF_SESSION_DATA,
    CONTENT_TYPE_MUSIC,
    CONTENT_TYPE_PODCAST,
    DEFAULT_AUDIO_FORMAT,
    ENTITY_ARTIST,
    ENTITY_COLLECTION,
    ENTITY_CONTENT,
    ENTITY_PLAYLIST,
    HLS_AUDIO_FORMAT,
    MAX_PAGES,
    PAGE_SIZE,
    RADIO_METADATA_INTERVAL,
    RECOMMENDATION_ROW_SIZE,
    TOP_TRACKS_LIMIT,
)
from .parsers import (
    get_audio_format,
    is_fully_played,
    parse_album,
    parse_artist,
    parse_playlist,
    parse_podcast,
    parse_podcast_episode,
    parse_radio,
    parse_release_date,
    parse_resume_position,
    parse_resume_timestamp,
    parse_track,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from datetime import datetime

    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.enums import ProviderFeature
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.constants import PlaylistPlayableItem
    from music_assistant.mass import MusicAssistant

# errors from a single (optional) API call that must not take a whole listing down
_API_ERRORS = (LoginFailed, MediaNotFoundError, ResourceTemporarilyUnavailable)

# stories are albums of (children's) audio stories, listed with their own sort
_STORIES_PARAMS: dict[str, str] = {"sort": "newStories", "with_contents": "0"}


@dataclass(frozen=True)
class _Row:
    """A recommendation row: where its items come from and how it is presented."""

    name: str
    translation_key: str
    icon: str
    # dashboard: key of the (cached) content type dashboard payload the app's home shows
    # listing: a dedicated listing endpoint with params
    source: str
    content_type: str = CONTENT_TYPE_MUSIC
    key: str = ""
    endpoint: str = ""
    params: dict[str, str] = field(default_factory=dict)
    # the profile permission (allowed map key) needed to show the row
    permission: str = CONTENT_TYPE_MUSIC


# row id -> row; the ids are stable, the frontend stores user preferences keyed on them
_ROWS: dict[str, _Row] = {
    "banners": _Row("Featured", "featured", "mdi-star", "dashboard", key="banners"),
    "by24Six": _Row("24six Presents", "presents", "mdi-creation", "dashboard", key="by24Six"),
    "releases": _Row("New Releases", "new_releases", "mdi-new-box", "dashboard", key="releases"),
    "trending": _Row("Trending Tracks", "trending", "mdi-fire", "dashboard", key="trending"),
    "recent": _Row("Recently Played", "recently_played", "mdi-history", "dashboard", key="recent"),
    "newAlbums": _Row("New Albums", "new_albums", "mdi-album", "dashboard", key="newAlbums"),
    "newSingles": _Row(
        "New Singles", "new_singles", "mdi-music-note", "dashboard", key="newSingles"
    ),
    "newStories": _Row(
        "New Stories",
        "new_stories",
        "mdi-book-open-page-variant",
        "dashboard",
        key="newStories",
        permission="stories",
    ),
    "playlists": _Row(
        "24six Playlists", "playlists", "mdi-playlist-music", "dashboard", key="playlists"
    ),
    "artists": _Row(
        "Popular Artists", "popular_artists", "mdi-account-music", "dashboard", key="artists"
    ),
    "newArtists": _Row(
        "New Artists", "new_artists", "mdi-account-star", "dashboard", key="newArtists"
    ),
    "continueListening": _Row(
        "Continue Listening",
        "continue_listening",
        "mdi-play-circle-outline",
        "listing",
        content_type=CONTENT_TYPE_PODCAST,
        endpoint=f"{CONTENT_TYPE_PODCAST}/content",
        params={"in_progress": "1", "no_pagination": "0"},
        permission=CONTENT_TYPE_PODCAST,
    ),
    "popularPodcasts": _Row(
        "Popular Podcasts",
        "popular_podcasts",
        "mdi-podcast",
        "dashboard",
        content_type=CONTENT_TYPE_PODCAST,
        key="popular",
        permission=CONTENT_TYPE_PODCAST,
    ),
    "trendingEpisodes": _Row(
        "Trending Episodes",
        "trending_episodes",
        "mdi-microphone",
        "dashboard",
        content_type=CONTENT_TYPE_PODCAST,
        key="trending",
        permission=CONTENT_TYPE_PODCAST,
    ),
    "newPodcasts": _Row(
        "New Podcast Episodes",
        "new_podcast_episodes",
        "mdi-podcast",
        "listing",
        content_type=CONTENT_TYPE_PODCAST,
        endpoint=f"{CONTENT_TYPE_PODCAST}/content",
        params={"sort": "newest", "no_pagination": "0"},
        permission=CONTENT_TYPE_PODCAST,
    ),
}


class TwentyFourSixProvider(MusicProvider):
    """Provider implementation for 24six."""

    api: TwentyFourSixAPIClient

    def __init__(
        self,
        mass: MusicAssistant,
        manifest: ProviderManifest,
        config: ProviderConfig,
        supported_features: set[ProviderFeature],
    ) -> None:
        """Initialize the 24six provider."""
        super().__init__(mass, manifest, config, supported_features)
        self.api = TwentyFourSixAPIClient(self)

    async def handle_async_init(self) -> None:
        """Handle async initialization of the provider."""
        for key in (CONF_EMAIL, CONF_PASSWORD, CONF_PROFILE_ID):
            if not self.get_setup_value(key):
                msg = "The 24six account and profile need to be set up first"
                raise LoginFailed(msg)
        await self.api.ensure_logged_in()

    async def unload(self, is_removed: bool = False) -> None:
        """
        Handle unload/close of the provider.

        :param is_removed: True when the provider is removed from the configuration.
        """
        if is_removed:
            await self.api.logout()
        await self.api.close()

    def update_session_data(self, session_data: str) -> None:
        """
        Persist the session data (token and server device id) to the setup data.

        :param session_data: JSON-encoded session data to store.
        """
        self._update_setup_data(CONF_SESSION_DATA, session_data)

    def update_device_id(self, device_id: str) -> None:
        """
        Persist the server-assigned device id to the setup data.

        :param device_id: Device identifier to store.
        """
        self._update_setup_data(CONF_DEVICE_ID, device_id)

    def update_device_serial(self, device_serial: str) -> None:
        """
        Persist the generated device serial to the setup data.

        :param device_serial: Device serial identifier to store.
        """
        self._update_setup_data(CONF_DEVICE_SERIAL, device_serial)

    @use_cache(3600)
    async def search(
        self,
        search_query: str,
        media_types: list[MediaType],
        limit: int = 5,
    ) -> SearchResults:
        """
        Perform a search on 24six.

        :param search_query: Search query.
        :param media_types: A list of media_types to include.
        :param limit: Number of items to return in the search (per type).
        """
        results = SearchResults()
        if not search_query.strip():
            # the API rejects an empty query with a validation error
            return results
        music_types = {MediaType.ARTIST, MediaType.ALBUM, MediaType.TRACK, MediaType.PLAYLIST}
        if music_types & set(media_types):
            data = await self.api.api_post(
                f"{CONTENT_TYPE_MUSIC}/search", {"q": search_query, "limit": limit}
            )
            if MediaType.ARTIST in media_types:
                results.artists = [
                    parse_artist(self, item) for item in _valid_items(data.get("artists"))[:limit]
                ]
            if MediaType.ALBUM in media_types:
                results.albums = [
                    parse_album(self, item)
                    for item in _valid_items(data.get("collections"))[:limit]
                ]
            if MediaType.TRACK in media_types:
                # the songs key was renamed to content in a later API revision
                songs = data.get("content") or data.get("songs")
                results.tracks = [parse_track(self, item) for item in _valid_items(songs)[:limit]]
            if MediaType.PLAYLIST in media_types:
                results.playlists = [
                    parse_playlist(self, item)
                    for item in _valid_items(data.get("playlists"))[:limit]
                ]
        if MediaType.PODCAST in media_types and self._profile_allows(CONTENT_TYPE_PODCAST):
            with contextlib.suppress(*_API_ERRORS):
                data = await self.api.api_post(
                    f"{CONTENT_TYPE_PODCAST}/search", {"q": search_query, "limit": limit}
                )
                results.podcasts = [
                    parse_podcast(self, item)
                    for item in _valid_items(data.get("collections"))[:limit]
                ]
        return results

    async def get_library_artists(self) -> AsyncGenerator[Artist]:
        """Retrieve library artists from the provider."""
        async for item in self._paginate(
            f"{CONTENT_TYPE_MUSIC}/artist", {"library": "1", "sort": "alpha"}
        ):
            yield parse_artist(self, item)

    async def get_library_albums(self) -> AsyncGenerator[Album]:
        """Retrieve library albums from the provider."""
        async for item in self._paginate(
            f"{CONTENT_TYPE_MUSIC}/collection",
            {"library": "1", "sort": "alpha", "with_contents": "0"},
        ):
            yield parse_album(self, item)

    async def get_library_tracks(self) -> AsyncGenerator[Track]:
        """Retrieve library tracks from the provider."""
        async for item in self._paginate(
            f"{CONTENT_TYPE_MUSIC}/content",
            {"library": "1", "no_pagination": "0", "sort": "alpha"},
        ):
            yield parse_track(self, item)

    async def get_library_playlists(self) -> AsyncGenerator[Playlist]:
        """Retrieve library/subscribed playlists from the provider."""
        async for item in self._paginate(
            f"{CONTENT_TYPE_MUSIC}/playlist", {"library": "1", "sort": "alpha"}
        ):
            yield parse_playlist(self, item)

    async def get_library_podcasts(self) -> AsyncGenerator[Podcast]:
        """Retrieve library podcasts from the provider."""
        if not self._profile_allows(CONTENT_TYPE_PODCAST):
            self.logger.debug("Profile may not access podcasts, skipping podcast library")
            return
        async for item in self._paginate(
            f"{CONTENT_TYPE_PODCAST}/collection",
            {"library": "1", "sort": "alpha", "with_contents": "0"},
        ):
            yield parse_podcast(self, item)

    async def get_library_radios(self) -> AsyncGenerator[Radio]:
        """Retrieve the radio stations offered by 24six."""
        if not self._profile_allows("radio"):
            self.logger.debug("Profile may not access radio, skipping radio stations")
            return
        for item in await self._get_radio_stations():
            yield parse_radio(self, item)

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Get full artist details by id."""
        data = await self._get_artist_data(prov_artist_id)
        artist_data = data.get("artist") or data
        if not artist_data.get("id"):
            msg = f"Artist {prov_artist_id} not found"
            raise MediaNotFoundError(msg)
        return parse_artist(self, artist_data)

    async def get_album(self, prov_album_id: str) -> Album:
        """Get full album details by id."""
        collection_data = await self._get_collection(CONTENT_TYPE_MUSIC, prov_album_id)
        return parse_album(self, collection_data)

    async def get_track(self, prov_track_id: str) -> Track:
        """Get full track details by id."""
        return parse_track(self, await self._get_content_data(CONTENT_TYPE_MUSIC, prov_track_id))

    async def get_playlist(self, prov_playlist_id: str) -> Playlist:
        """Get full playlist details by id."""
        playlist_data = await self._get_playlist_page(prov_playlist_id, 1)
        return parse_playlist(self, playlist_data)

    async def get_podcast(self, prov_podcast_id: str) -> Podcast:
        """Get full podcast details by id."""
        collection_data = await self._get_collection(CONTENT_TYPE_PODCAST, prov_podcast_id)
        return parse_podcast(self, collection_data)

    async def get_podcast_episode(self, prov_episode_id: str) -> PodcastEpisode:
        """Get full podcast episode details by id."""
        data = await self._get_content_data(CONTENT_TYPE_PODCAST, prov_episode_id)
        return parse_podcast_episode(self, data)

    async def get_radio(self, prov_radio_id: str) -> Radio:
        """Get full radio station details by id."""
        for item in await self._get_radio_stations():
            if str(item.get("id")) == prov_radio_id:
                return parse_radio(self, item)
        msg = f"Radio station {prov_radio_id} not found"
        raise MediaNotFoundError(msg)

    async def get_album_tracks(self, prov_album_id: str) -> list[Track]:
        """Get album tracks for the given album id."""
        collection_data = await self._get_collection(CONTENT_TYPE_MUSIC, prov_album_id)
        album_artists = [
            parse_artist(self, artist_data)
            for artist_data in _valid_items(collection_data.get("artists"))
        ]
        return [
            parse_track(self, content, fallback_artists=album_artists)
            for content in _valid_items(collection_data.get("contents"))
        ]

    @use_cache(3600 * 24, allow_expired_cache=True)
    async def get_artist_albums(self, prov_artist_id: str) -> list[Album]:
        """Get a list of all albums for the given artist."""
        return [
            parse_album(self, item)
            async for item in self._paginate(
                f"{CONTENT_TYPE_MUSIC}/collection",
                {
                    "artist_id": prov_artist_id,
                    "sort": "popular",
                    "use_popularity_logic": "1",
                    "with_contents": "0",
                },
            )
        ]

    @use_cache(3600 * 24, allow_expired_cache=True)
    async def get_artist_toptracks(self, prov_artist_id: str) -> list[Track]:
        """Get the most popular tracks for the given artist."""
        data = await self.api.api_get(
            f"{CONTENT_TYPE_MUSIC}/content",
            params={
                "artist_id": prov_artist_id,
                "no_pagination": "0",
                "sort": "popular",
                "page": "1",
                "per_page": str(TOP_TRACKS_LIMIT),
            },
        )
        return [parse_track(self, item) for item in _valid_items(data.get("data"))]

    async def get_playlist_tracks(
        self, prov_playlist_id: str, page: int = 0
    ) -> Sequence[PlaylistPlayableItem]:
        """
        Get the tracks of a playlist, one page at a time.

        :param prov_playlist_id: The provider playlist id.
        :param page: Zero-based page number (the API counts pages from 1).
        """
        api_page = page + 1
        if api_page > 1:
            first_page = await self._get_playlist_page(prov_playlist_id, 1)
            total_pages = _total_pages(first_page.get("pagination"))
            if total_pages is not None and api_page > total_pages:
                return []
        playlist_data = await self._get_playlist_page(prov_playlist_id, api_page)
        contents = _valid_items(playlist_data.get("contents"))
        # the API only paginates when a page size is reported, otherwise page 1 holds all
        page_size = _page_size(playlist_data.get("pagination"))
        if api_page > 1 and page_size is None:
            return []
        offset = (api_page - 1) * (page_size or 0)
        tracks: list[Track] = []
        for idx, content in enumerate(contents, start=offset + 1):
            track = parse_track(self, content)
            track.position = idx
            tracks.append(track)
        return tracks

    async def get_podcast_episodes(self, prov_podcast_id: str) -> AsyncGenerator[PodcastEpisode]:
        """
        Get all episodes of the given podcast.

        :param prov_podcast_id: The provider podcast id.
        """
        podcast = await self.get_podcast(prov_podcast_id)
        episodes = [
            item
            async for item in self._paginate(
                f"{CONTENT_TYPE_PODCAST}/content",
                {"collection_id": prov_podcast_id, "sort": "newest", "no_pagination": "0"},
            )
        ]
        # the listing carries no episode number, so rank on the release date
        positions = rank_episodes_by_date(
            [parse_release_date(item, created_fallback=True) for item in episodes]
        )
        for position, item in zip(positions, episodes, strict=True):
            yield parse_podcast_episode(self, item, position=position, podcast=podcast)

    async def get_resume_position(
        self, item_id: str, media_type: MediaType
    ) -> tuple[bool, int, datetime | None]:
        """
        Get the resume point of a podcast episode from the profile's listening history.

        :param item_id: The provider episode id.
        :param media_type: The media type (only podcast episodes are supported).
        """
        if media_type != MediaType.PODCAST_EPISODE:
            return (False, 0, None)
        try:
            data = await self._fetch_content_data(CONTENT_TYPE_PODCAST, item_id)
        except (*_API_ERRORS, KeyError) as err:
            # resume is best-effort: a transient failure must not break playback
            self.logger.warning("Could not fetch resume position for %s: %s", item_id, err)
            return (False, 0, None)
        position = parse_resume_position(data)
        if position is None:
            return (False, 0, None)
        duration = int(data.get("length") or data.get("duration") or 0)
        return (is_fully_played(position, duration), position * 1000, parse_resume_timestamp(data))

    async def library_add(self, item: MediaItemType) -> bool:
        """Add an item to the provider's library. Return true on success."""
        prov_item_id = self._get_prov_item_id(item)
        endpoint = self._library_endpoint(item.media_type, prov_item_id)
        if not endpoint:
            return False
        try:
            await self.api.api_post(endpoint)
        except (MediaNotFoundError, ResourceTemporarilyUnavailable) as err:
            self.logger.debug("Failed to add %s to library: %s", prov_item_id, err)
            return False
        return True

    async def library_remove(self, prov_item_id: str, media_type: MediaType) -> bool:
        """Remove an item from the provider's library. Return true on success."""
        if media_type == MediaType.PLAYLIST:
            # an owned playlist is deleted, any other playlist is only unsubscribed
            try:
                await self.api.api_delete(f"{CONTENT_TYPE_MUSIC}/playlist/{prov_item_id}")
                return True
            except MediaNotFoundError, ResourceTemporarilyUnavailable:
                pass
        endpoint = self._library_endpoint(media_type, prov_item_id)
        if not endpoint:
            return False
        try:
            await self.api.api_delete(endpoint)
        except (MediaNotFoundError, ResourceTemporarilyUnavailable) as err:
            self.logger.debug("Failed to remove %s from library: %s", prov_item_id, err)
            return False
        return True

    async def set_favorite(self, prov_item_id: str, media_type: MediaType, favorite: bool) -> None:
        """
        Set the favorite status for an item on 24six.

        :param prov_item_id: The provider item id.
        :param media_type: The media type of the item.
        :param favorite: Whether to add or remove the favorite.
        """
        content_type, entity = self._entity_for(media_type)
        if not entity or media_type == MediaType.PLAYLIST:
            return
        endpoint = f"{content_type}/{entity}/{prov_item_id}/favorite"
        if favorite:
            await self.api.api_post(endpoint)
        else:
            await self.api.api_delete(endpoint)

    async def create_playlist(self, name: str, media_types: set[MediaType]) -> Playlist:
        """Create a new playlist on the provider."""
        data = await self.api.api_post(f"{CONTENT_TYPE_MUSIC}/playlist", params={"name": name})
        # the create response does not flag ownership, but a playlist we created is ours
        return parse_playlist(self, {**(data.get("playlist") or data), "mine": True})

    async def add_playlist_tracks(self, prov_playlist_id: str, prov_track_ids: list[str]) -> None:
        """Add tracks to an existing playlist."""
        params: list[tuple[str, str]] = [("content[]", tid) for tid in prov_track_ids]
        params.append(("force", "0"))
        await self.api.api_post(
            f"{CONTENT_TYPE_MUSIC}/playlist/{prov_playlist_id}/add", params=params
        )
        await self._invalidate_playlist_cache(prov_playlist_id)

    async def remove_playlist_tracks(
        self, prov_playlist_id: str, positions_to_remove: tuple[int, ...]
    ) -> None:
        """
        Remove tracks from a playlist by position.

        The 24six API has no endpoint to remove individual tracks, so the full
        track list is replaced with the remaining tracks.

        :param prov_playlist_id: The provider playlist id.
        :param positions_to_remove: 1-based positions of the tracks to remove.
        """
        remaining_ids = [
            str(track["id"])
            for pos, track in enumerate(await self._get_all_playlist_contents(prov_playlist_id), 1)
            if pos not in set(positions_to_remove)
        ]
        if not remaining_ids:
            # the API validates content[] entries but treats a missing list as "no change",
            # so a playlist cannot be emptied through this endpoint
            msg = "24six cannot remove the last track of a playlist, delete the playlist instead"
            raise UnsupportedFeaturedException(msg)
        playlist_name = (await self._get_playlist_page(prov_playlist_id, 1)).get("title") or ""
        params: list[tuple[str, str]] = [("content[]", tid) for tid in remaining_ids]
        params.append(("force", "0"))
        params.append(("name", playlist_name))
        await self.api.api_patch(f"{CONTENT_TYPE_MUSIC}/playlist/{prov_playlist_id}", params=params)
        await self._invalidate_playlist_cache(prov_playlist_id)

    async def get_similar_tracks(self, prov_track_id: str, limit: int = 25) -> list[Track]:
        """
        Get tracks that 24six recommends to play after the given track.

        :param prov_track_id: The provider track id.
        :param limit: Maximum number of tracks to return.
        """
        data = await self.api.api_post(
            f"{CONTENT_TYPE_MUSIC}/content/recommended",
            {"queue": [prov_track_id], "limit": limit, "ai": 0},
        )
        items = data.get("data") or data.get("content")
        return [parse_track(self, item) for item in _valid_items(items)[:limit]]

    async def get_similar_artists(self, prov_artist_id: str, limit: int = 25) -> list[Artist]:
        """
        Get artists similar to the given artist.

        :param prov_artist_id: The provider artist id.
        :param limit: Maximum number of artists to return.
        """
        # the artist landing page carries the curated similar artists, fall back to the
        # similar-artist filter of the artist listing when it has none
        landing = await self._get_artist_data(prov_artist_id)
        similar = _valid_items(landing.get("similar"))
        if not similar:
            data = await self.api.api_get(
                f"{CONTENT_TYPE_MUSIC}/artist",
                params={"similar_artist_id": prov_artist_id, "page": "1", "per_page": str(limit)},
            )
            similar = _valid_items(data.get("data"))
        return [parse_artist(self, item) for item in similar[:limit]]

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Get the stream details for a track, podcast episode or radio station."""
        # playback must not queue behind library/browse traffic: resolve the stream
        # without the request throttle (the retries on transient errors still apply)
        async with self.api.throttler.bypass():
            if media_type == MediaType.RADIO:
                stream_url = await self.api.api_get_stream_url(
                    f"radio/{item_id}/play", {"livestream": "1", "format": HLS_AUDIO_FORMAT}
                )
            else:
                content_type = (
                    CONTENT_TYPE_PODCAST
                    if media_type == MediaType.PODCAST_EPISODE
                    else CONTENT_TYPE_MUSIC
                )
                stream_url = await self.api.api_get_stream_url(
                    f"content/{item_id}/play",
                    {"format": await self._preferred_audio_format(content_type, item_id)},
                )
        is_hls = urlparse(stream_url).path.endswith(".m3u8")
        details = StreamDetails(
            provider=self.instance_id,
            item_id=item_id,
            audio_format=AudioFormat(content_type=ContentType.AAC),
            media_type=media_type,
            stream_type=StreamType.HLS if is_hls else StreamType.HTTP,
            allow_seek=media_type != MediaType.RADIO,
            can_seek=media_type != MediaType.RADIO,
            path=stream_url,
        )
        if media_type == MediaType.RADIO:
            details.stream_metadata_update_callback = self._update_radio_metadata
            details.stream_metadata_update_interval = RADIO_METADATA_INTERVAL
        return details

    async def on_played(
        self,
        media_type: MediaType,
        prov_item_id: str,
        fully_played: bool,
        position: int,
        media_item: MediaItemType,
        is_playing: bool = False,
    ) -> None:
        """
        Report playback progress to 24six.

        :param media_type: The media type that is played.
        :param prov_item_id: The provider item id.
        :param fully_played: Whether the item has been fully played.
        :param position: The current position in seconds.
        :param media_item: The full media item details.
        :param is_playing: Whether the item is currently playing.
        """
        if media_type not in (MediaType.TRACK, MediaType.PODCAST_EPISODE):
            return
        if is_playing:
            # the app logs a play once, when it ends; the periodic progress ticks would
            # each count as a play on the server, inflating play counts and charts
            return
        if position <= 0 and not fully_played:
            # the item was marked unplayed in the UI, nothing was listened to
            return
        # the API wants the seconds listened and the position they stopped at; the
        # elapsed playback time is the closest value we have for both
        await self.api.log_playback(item_id=prov_item_id, seconds=position, current=position)

    async def browse(self, path: str) -> Sequence[MediaItemType | ItemMapping | BrowseFolder]:
        """
        Browse this provider's items.

        :param path: The path to browse, (e.g. provider_id://artists).
        """
        prefix, _, subpath = path.partition("://")
        path_parts = subpath.split("/") if subpath else []
        folder = path_parts[0] if path_parts else None

        if folder == "category" and len(path_parts) > 1:
            # the category landing page only carries a teaser of releases, list them all
            return [
                parse_album(self, item)
                async for item in self._paginate(
                    f"{CONTENT_TYPE_MUSIC}/collection",
                    {"category_id": path_parts[1], "sort": "popular", "with_contents": "0"},
                )
            ]

        if folder == "stories":
            return [parse_album(self, item) for item in await self._get_story_albums()]

        if folder == "categories":
            data = await self.api.api_get(
                f"{CONTENT_TYPE_MUSIC}/category",
                params={"page": "1", "per_page": "100", "sort": "popular"},
            )
            return [
                BrowseFolder(
                    item_id=str(category["id"]),
                    provider=self.instance_id,
                    path=f"{prefix}://category/{category['id']}",
                    name=category.get("title") or "",
                )
                for category in _valid_items(data.get("data"))
            ]

        result = list(await super().browse(path))
        # only add the Categories and Stories folders to the root-level listing
        if not folder:
            result.append(
                BrowseFolder(
                    item_id="categories",
                    provider=self.instance_id,
                    path=f"{prefix}://categories",
                    name="Categories",
                    translation_key="categories",
                )
            )
            if self._profile_allows("stories"):
                result.append(
                    BrowseFolder(
                        item_id="stories",
                        provider=self.instance_id,
                        path=f"{prefix}://stories",
                        name="Stories",
                        translation_key="stories",
                        is_playable=True,
                    )
                )
        return result

    async def get_recommendations(self) -> list[RecommendationFolder]:
        """Get this provider's recommendation rows, without items."""
        return [
            RecommendationFolder(
                item_id=row_id,
                provider=self.instance_id,
                name=row.name,
                translation_key=row.translation_key,
                icon=row.icon,
                is_playable=True,
            )
            for row_id, row in _ROWS.items()
            if self._profile_allows(row.permission)
        ]

    async def get_recommendation_items(
        self, item_id: str
    ) -> UniqueList[MediaItemType | ItemMapping | BrowseFolder]:
        """
        Get the items for a single recommendation row.

        :param item_id: The item_id of the row, as returned by get_recommendations.
        """
        items: UniqueList[MediaItemType | ItemMapping | BrowseFolder] = UniqueList()
        row = _ROWS.get(item_id)
        if row is None:
            return items
        if row.source == "dashboard":
            dashboard = await self._get_dashboard(row.content_type)
            if row.key == "banners":
                for banner in _valid_items(dashboard.get("banners"), key="entity_id"):
                    if resolved := await self._resolve_banner(banner):
                        items.append(resolved)
                return items
            entries = _valid_items(dashboard.get(row.key))
        else:
            entries = await self._get_listing_row(item_id)
        for entry in entries:
            if parsed := self._parse_by_type(entry, row.content_type):
                items.append(parsed)
        await self._enrich_tracks_duration(items)
        return items

    @use_cache(3600 * 24 * 30)
    async def _get_artist_data(self, prov_artist_id: str) -> dict[str, Any]:
        """Fetch and cache the raw artist landing page from the API."""
        return await self.api.api_get(f"{CONTENT_TYPE_MUSIC}/artist/{prov_artist_id}")

    @use_cache(3600 * 24 * 30)
    async def _get_collection_data(
        self, content_type: str, prov_collection_id: str
    ) -> dict[str, Any]:
        """Fetch and cache the raw collection (album or podcast) landing page from the API."""
        return await self.api.api_get(f"{content_type}/collection/{prov_collection_id}")

    async def _get_collection(self, content_type: str, prov_collection_id: str) -> dict[str, Any]:
        """Return the collection object of a collection landing page, or raise when missing."""
        data = await self._get_collection_data(content_type, prov_collection_id)
        collection_data = data.get("collection") or data
        if not collection_data.get("id"):
            msg = f"Collection {prov_collection_id} not found"
            raise MediaNotFoundError(msg)
        return collection_data

    @use_cache(3600 * 24 * 30)
    async def _get_content_data(self, content_type: str, prov_content_id: str) -> dict[str, Any]:
        """Fetch and cache the raw content (track or episode) object from the API."""
        return await self._fetch_content_data(content_type, prov_content_id)

    async def _fetch_content_data(self, content_type: str, prov_content_id: str) -> dict[str, Any]:
        """Fetch the raw content (track or episode) object from the API, bypassing the cache."""
        data = await self.api.api_post(f"{content_type}/content/{prov_content_id}")
        content_data = data.get("content") or data
        if not content_data.get("id"):
            msg = f"Content {prov_content_id} not found"
            raise MediaNotFoundError(msg)
        return content_data

    @use_cache(3600 * 3)
    async def _get_playlist_page(self, prov_playlist_id: str, api_page: int) -> dict[str, Any]:
        """Fetch and cache one page of a playlist landing page from the API."""
        data = await self.api.api_get(
            f"{CONTENT_TYPE_MUSIC}/playlist/{prov_playlist_id}", params={"page": str(api_page)}
        )
        playlist_data = data.get("playlist") or data
        if not playlist_data.get("id"):
            msg = f"Playlist {prov_playlist_id} not found"
            raise MediaNotFoundError(msg)
        return playlist_data

    async def _get_all_playlist_contents(self, prov_playlist_id: str) -> list[dict[str, Any]]:
        """Return the raw contents of a playlist across all of its pages."""
        contents: list[dict[str, Any]] = []
        api_page = 1
        while api_page <= MAX_PAGES:
            playlist_data = await self._get_playlist_page(prov_playlist_id, api_page)
            contents.extend(_valid_items(playlist_data.get("contents")))
            total_pages = _total_pages(playlist_data.get("pagination"))
            if total_pages is None or api_page >= total_pages:
                break
            api_page += 1
        return contents

    async def _invalidate_playlist_cache(self, prov_playlist_id: str) -> None:
        """Drop the cached playlist pages after the playlist was modified."""
        api_page = 1
        while api_page <= MAX_PAGES:
            cache_key = f"_get_playlist_page.{prov_playlist_id}.{api_page}"
            if await self.mass.cache.get(cache_key, provider=self.instance_id) is None:
                break
            await self.mass.cache.delete(cache_key, provider=self.instance_id)
            api_page += 1

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_story_albums(self) -> list[dict[str, Any]]:
        """Fetch and cache the raw story albums across all pages of the listing."""
        return [
            item
            async for item in self._paginate(f"{CONTENT_TYPE_MUSIC}/collection", _STORIES_PARAMS)
        ]

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_listing_row(self, row_id: str) -> list[dict[str, Any]]:
        """Fetch and cache the raw items of a recommendation row served by a listing endpoint."""
        row = _ROWS[row_id]
        try:
            data = await self.api.api_get(
                row.endpoint,
                params={**row.params, "page": "1", "per_page": str(RECOMMENDATION_ROW_SIZE)},
            )
        except _API_ERRORS as err:
            self.logger.debug("Failed to fetch recommendation row %s: %s", row_id, err)
            return []
        return _valid_items(data.get("data"))[:RECOMMENDATION_ROW_SIZE]

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_dashboard(self, content_type: str) -> dict[str, Any]:
        """Fetch and cache the dashboard (home screen) payload of a content type."""
        try:
            return await self.api.api_get(content_type, params={"use_popularity_logic": "1"})
        except _API_ERRORS as err:
            self.logger.debug("Failed to fetch %s dashboard: %s", content_type, err)
            return {}

    async def _update_radio_metadata(
        self, stream_details: StreamDetails, elapsed_time: int
    ) -> None:
        """
        Refresh the now-playing metadata of a radio station from the live dashboard.

        :param stream_details: The stream details of the playing station to update.
        :param elapsed_time: Elapsed playback time in seconds (unused).
        """
        try:
            data = await self.api.api_get("live/dashboard", params={"use_popularity_logic": "1"})
        except _API_ERRORS as err:
            self.logger.debug("Could not refresh radio metadata: %s", err)
            return
        stations = _radio_stations(data)
        station = next(
            (item for item in stations if str(item.get("id")) == stream_details.item_id), None
        )
        now_playing = station.get("radio_now") if station else None
        if not isinstance(now_playing, dict) or not now_playing.get("title"):
            return
        has_elapsed = now_playing.get("elapsed") is not None
        stream_details.stream_metadata = StreamMetadata(
            title=str(now_playing["title"]),
            artist=now_playing.get("subtitle") or None,
            album=now_playing.get("album") or None,
            image_url=now_playing.get("img") or None,
            duration=int(now_playing["duration"]) if now_playing.get("duration") else None,
            elapsed_time=int(now_playing["elapsed"]) if has_elapsed else None,
            elapsed_time_last_updated=time.time() if has_elapsed else None,
        )

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_radio_stations(self) -> list[dict[str, Any]]:
        """Fetch and cache the radio stations from the live dashboard."""
        try:
            data = await self.api.api_get("live/dashboard", params={"use_popularity_logic": "1"})
        except _API_ERRORS as err:
            self.logger.debug("Failed to fetch live dashboard: %s", err)
            return []
        return _radio_stations(data)

    async def _preferred_audio_format(self, content_type: str, prov_content_id: str) -> str:
        """Return the stream format to request for a content item, as the app would."""
        try:
            content_data = await self._get_content_data(content_type, prov_content_id)
        except _API_ERRORS:
            return DEFAULT_AUDIO_FORMAT
        return get_audio_format(content_data) or DEFAULT_AUDIO_FORMAT

    async def _paginate(
        self, endpoint: str, params: dict[str, str]
    ) -> AsyncGenerator[dict[str, Any]]:
        """
        Paginate a listing endpoint, yielding the items with a valid id.

        :param endpoint: The API endpoint to paginate.
        :param params: Extra query parameters (page is managed automatically, per_page
            defaults to PAGE_SIZE but can be overridden via params).
        """
        page = 1
        while page <= MAX_PAGES:
            data = await self.api.api_get(
                endpoint, params={"per_page": str(PAGE_SIZE), **params, "page": str(page)}
            )
            items = _valid_items(data.get("data"))
            pagination = (data.get("meta") or {}).get("pagination") or {}
            self.logger.debug(
                "Fetched %s items from %s page %s (pagination: %s)",
                len(items),
                endpoint,
                page,
                pagination or "none",
            )
            if not items:
                break
            for item in items:
                yield item
            if not _has_next_page(pagination, page, len(items)):
                break
            page += 1

    async def _enrich_tracks_duration(
        self, items: UniqueList[MediaItemType | ItemMapping | BrowseFolder]
    ) -> None:
        """Enrich tracks missing a duration by fetching their full details in parallel."""
        indices = [
            idx for idx, item in enumerate(items) if isinstance(item, Track) and not item.duration
        ]
        if not indices:
            return
        results = await asyncio.gather(
            *(self.get_track(items[idx].item_id) for idx in indices), return_exceptions=True
        )
        for idx, result in zip(indices, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.debug("Failed to enrich track %s: %s", items[idx].item_id, result)
                continue
            items[idx] = result

    def _parse_by_type(
        self, item: dict[str, Any], default_content_type: str = CONTENT_TYPE_MUSIC
    ) -> MediaItemType | None:
        """
        Parse a v3 API item to the matching media item based on its type field.

        :param item: The raw API item.
        :param default_content_type: Content type to assume when the item does not carry one.
        """
        item_type = item.get("type", "")
        content_type = item.get("content_type") or default_content_type
        if item_type == "collection":
            if content_type == CONTENT_TYPE_PODCAST:
                return parse_podcast(self, item)
            return parse_album(self, item)
        if item_type == "content":
            if content_type == CONTENT_TYPE_PODCAST and item.get("collection_id"):
                return parse_podcast_episode(self, item)
            return parse_track(self, item)
        if item_type == "playlist":
            return parse_playlist(self, item)
        if item_type == "artist":
            return parse_artist(self, item)
        if item_type == "radio":
            return parse_radio(self, item)
        return None

    async def _resolve_banner(self, banner: dict[str, Any]) -> MediaItemType | None:
        """Resolve a homepage banner (an entity reference) to its full media item."""
        entity_id = str(banner["entity_id"])
        entity_type = banner.get("entity_type", "")
        try:
            if entity_type == ENTITY_PLAYLIST:
                return await self.get_playlist(entity_id)
            if entity_type == ENTITY_COLLECTION:
                return await self.get_album(entity_id)
            if entity_type == ENTITY_ARTIST:
                return await self.get_artist(entity_id)
            if entity_type == ENTITY_CONTENT:
                return await self.get_track(entity_id)
        except _API_ERRORS:
            return None
        return None

    def _profile_allows(self, content_type: str) -> bool:
        """
        Return whether the logged-in profile may access the given content type.

        Unknown (e.g. after a restored session without profile details) counts as allowed.

        :param content_type: The content type key of the profile's allowed map.
        """
        allowed = self.api.profile.get("allowed")
        if not isinstance(allowed, dict) or content_type not in allowed:
            return True
        return bool(allowed[content_type])

    def _library_endpoint(self, media_type: MediaType, prov_item_id: str | None) -> str | None:
        """Return the library endpoint for an item, or None when unsupported."""
        content_type, entity = self._entity_for(media_type)
        if not entity or not prov_item_id:
            return None
        return f"{content_type}/library/{entity}/{prov_item_id}"

    @staticmethod
    def _entity_for(media_type: MediaType) -> tuple[str, str | None]:
        """Map a media type to the API content type and entity type."""
        entity_map: dict[MediaType, tuple[str, str]] = {
            MediaType.ARTIST: (CONTENT_TYPE_MUSIC, ENTITY_ARTIST),
            MediaType.ALBUM: (CONTENT_TYPE_MUSIC, ENTITY_COLLECTION),
            MediaType.TRACK: (CONTENT_TYPE_MUSIC, ENTITY_CONTENT),
            MediaType.PLAYLIST: (CONTENT_TYPE_MUSIC, ENTITY_PLAYLIST),
            MediaType.PODCAST: (CONTENT_TYPE_PODCAST, ENTITY_COLLECTION),
            MediaType.PODCAST_EPISODE: (CONTENT_TYPE_PODCAST, ENTITY_CONTENT),
        }
        return entity_map.get(media_type, (CONTENT_TYPE_MUSIC, None))

    def _get_prov_item_id(self, item: MediaItemType) -> str | None:
        """Get the provider item id from a media item's provider mappings."""
        for mapping in item.provider_mappings:
            if mapping.provider_instance == self.instance_id:
                item_id: str = mapping.item_id
                return item_id
        return None


def _radio_stations(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the radio stations of a live dashboard payload."""
    audio = dashboard.get("audio") or {}
    return _valid_items(audio.get("radio") or dashboard.get("radio"))


def _valid_items(items: Any, key: str = "id") -> list[dict[str, Any]]:
    """Return the dict items of an API list that carry the given key."""
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get(key)]


def _total_pages(pagination: Any) -> int | None:
    """Return the total number of pages from a pagination object, if known."""
    if not isinstance(pagination, dict):
        return None
    for key in ("total_pages", "last_page"):
        with contextlib.suppress(TypeError, ValueError):
            if pagination.get(key) is not None:
                return int(pagination[key])
    # the API reports totals and a page size rather than a page count
    with contextlib.suppress(TypeError, ValueError, ZeroDivisionError):
        if pagination.get("total") is not None and pagination.get("per_page"):
            return -(-int(pagination["total"]) // int(pagination["per_page"]))
    return None


def _page_size(pagination: Any) -> int | None:
    """Return the page size from a pagination object, if known."""
    if not isinstance(pagination, dict):
        return None
    with contextlib.suppress(TypeError, ValueError):
        if pagination.get("per_page") is not None:
            return int(pagination["per_page"])
    return None


def _has_next_page(pagination: dict[str, Any], page: int, item_count: int) -> bool:
    """
    Return whether a listing has another page after the given one.

    :param pagination: The pagination object from the response metadata.
    :param page: The page that was just fetched.
    :param item_count: The number of items on that page.
    """
    if "next_page" in pagination:
        return bool(pagination["next_page"])
    if (total_pages := _total_pages(pagination)) is not None:
        return page < total_pages
    if (page_size := _page_size(pagination)) is not None:
        return item_count >= page_size
    return False
