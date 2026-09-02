"""24six music provider implementation."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from music_assistant_models.enums import ContentType, MediaType, StreamType
from music_assistant_models.errors import (
    LoginFailed,
    MediaNotFoundError,
    MusicAssistantError,
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
    BROWSE_LIST_LIMIT,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PROFILE_ID,
    CONTENT_TYPE_MUSIC,
    CONTENT_TYPE_PODCAST,
    DEFAULT_AUDIO_FORMAT,
    ENTITY_ARTIST,
    ENTITY_COLLECTION,
    ENTITY_CONTENT,
    ENTITY_PLAYLIST,
    ENTITY_RADIO,
    HLS_AUDIO_FORMAT,
    MAX_PAGES,
    PAGE_SIZE,
    RADIO_METADATA_INTERVAL,
    RADIO_METADATA_MAX_INTERVAL,
    RECOMMENDATION_ROW_SIZE,
    RECOMMENDATION_ROWS,
    STORIES_PARAMS,
    TOP_TRACKS_LIMIT,
)
from .helpers import has_next_page, page_size, radio_stations, total_pages, valid_items
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

# browse folders offered next to the library folders of the base class
_FOLDER_CATEGORIES = "categories"
_FOLDER_CATEGORY = "category"
_FOLDER_STORIES = "stories"
_FOLDER_RADIO = "radio"


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
        self.api = TwentyFourSixAPIClient(self, self._update_setup_data)
        # resume points handed out for podcast episodes, so a play that started
        # mid-way reports only the seconds listened since then
        self._resume_starts: dict[str, int] = {}

    @property
    def supported_media_types(self) -> set[MediaType]:
        """Return the media types this provider can serve."""
        # radio stations are browsed and played but never synced to the library
        return super().supported_media_types | {MediaType.RADIO}

    async def handle_async_init(self) -> None:
        """Handle async initialization of the provider."""
        for key in (CONF_EMAIL, CONF_PASSWORD, CONF_PROFILE_ID):
            if not self.get_setup_value(key):
                raise LoginFailed("The 24six account and profile need to be set up first")
        await self.api.ensure_logged_in()

    async def unload(self, is_removed: bool = False) -> None:
        """
        Handle unload/close of the provider.

        :param is_removed: True when the provider is removed from the configuration.
        """
        if is_removed:
            await self.api.logout()

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
                    parse_artist(self, item) for item in valid_items(data.get("artists"))[:limit]
                ]
            if MediaType.ALBUM in media_types:
                results.albums = [
                    parse_album(self, item) for item in valid_items(data.get("collections"))[:limit]
                ]
            if MediaType.TRACK in media_types:
                results.tracks = [
                    parse_track(self, item) for item in valid_items(data.get("content"))[:limit]
                ]
            if MediaType.PLAYLIST in media_types:
                results.playlists = [
                    parse_playlist(self, item)
                    for item in valid_items(data.get("playlists"))[:limit]
                ]
        if MediaType.PODCAST in media_types and self.api.profile_allows(CONTENT_TYPE_PODCAST):
            data = await self.api.api_post(
                f"{CONTENT_TYPE_PODCAST}/search", {"q": search_query, "limit": limit}
            )
            results.podcasts = [
                parse_podcast(self, item) for item in valid_items(data.get("collections"))[:limit]
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
        if not self.api.profile_allows(CONTENT_TYPE_PODCAST):
            self.logger.debug("Profile may not access podcasts, skipping podcast library")
            return
        async for item in self._paginate(
            f"{CONTENT_TYPE_PODCAST}/collection",
            {"library": "1", "sort": "alpha", "with_contents": "0"},
        ):
            yield parse_podcast(self, item)

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Get full artist details by id."""
        data = await self._get_artist_data(prov_artist_id)
        artist_data = data.get("artist") or data
        if not artist_data.get("id"):
            raise MediaNotFoundError(f"Artist {prov_artist_id} not found")
        return parse_artist(self, artist_data)

    async def get_album(self, prov_album_id: str) -> Album:
        """Get full album details by id."""
        return parse_album(self, await self._get_collection(CONTENT_TYPE_MUSIC, prov_album_id))

    async def get_track(self, prov_track_id: str) -> Track:
        """Get full track details by id."""
        return parse_track(self, await self._get_cached_track_data(prov_track_id))

    async def get_playlist(self, prov_playlist_id: str) -> Playlist:
        """Get full playlist details by id."""
        return parse_playlist(self, await self._get_playlist_page(prov_playlist_id, 1))

    async def get_podcast(self, prov_podcast_id: str) -> Podcast:
        """Get full podcast details by id."""
        return parse_podcast(
            self, await self._get_collection(CONTENT_TYPE_PODCAST, prov_podcast_id)
        )

    async def get_podcast_episode(self, prov_episode_id: str) -> PodcastEpisode:
        """Get full podcast episode details by id."""
        return parse_podcast_episode(self, await self._get_cached_episode_data(prov_episode_id))

    async def get_radio(self, prov_radio_id: str) -> Radio:
        """Get full radio station details by id."""
        for item in await self._get_radio_stations():
            if str(item.get("id")) == prov_radio_id:
                return parse_radio(self, item)
        raise MediaNotFoundError(f"Radio station {prov_radio_id} not found")

    async def get_album_tracks(self, prov_album_id: str) -> list[Track]:
        """Get album tracks for the given album id."""
        collection_data = await self._get_collection(CONTENT_TYPE_MUSIC, prov_album_id)
        album_artists = [
            parse_artist(self, artist_data)
            for artist_data in valid_items(collection_data.get("artists"))
        ]
        return [
            parse_track(self, content, fallback_artists=album_artists)
            for content in valid_items(collection_data.get("contents"))
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
    async def get_artist_tracks(self, prov_artist_id: str) -> list[Track]:
        """Get a list of all tracks for the given artist."""
        return [
            parse_track(self, item)
            async for item in self._paginate(
                f"{CONTENT_TYPE_MUSIC}/content",
                {"artist_id": prov_artist_id, "no_pagination": "0", "sort": "alpha"},
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
        return [parse_track(self, item) for item in valid_items(data.get("data"))]

    async def get_artist_topalbums(self, prov_artist_id: str) -> list[Album]:
        """Get the most popular albums for the given artist."""
        landing = await self._get_artist_data(prov_artist_id)
        return [parse_album(self, item) for item in valid_items(landing.get("albums"))]

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
            pages = total_pages(first_page.get("pagination"))
            if pages is not None and api_page > pages:
                return []
        playlist_data = await self._get_playlist_page(prov_playlist_id, api_page)
        # the API only paginates when a page size is reported, otherwise page 1 holds all
        size = page_size(playlist_data.get("pagination"))
        if api_page > 1 and size is None:
            return []
        offset = (api_page - 1) * (size or 0)
        tracks: list[Track] = []
        for idx, content in enumerate(valid_items(playlist_data.get("contents")), start=offset + 1):
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
        episodes = await self._get_podcast_episode_items(prov_podcast_id)
        # the listing carries no episode number, so rank on the publication date
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
        data = await self._fetch_content(CONTENT_TYPE_PODCAST, item_id)
        position = parse_resume_position(data) or 0
        self._resume_starts[item_id] = position
        duration = int(data.get("length") or data.get("duration") or 0)
        return (is_fully_played(position, duration), position * 1000, parse_resume_timestamp(data))

    async def library_add(self, item: MediaItemType) -> bool:
        """Add an item to the provider's library. Return true on success."""
        endpoint = self._library_endpoint(item.media_type, self._prov_item_id(item))
        if not endpoint:
            return False
        await self.api.api_post(endpoint)
        return True

    async def library_remove(self, prov_item_id: str, media_type: MediaType) -> bool:
        """Remove an item from the provider's library. Return true on success."""
        if media_type == MediaType.PLAYLIST:
            # an owned playlist is deleted, any other playlist is only unsubscribed
            playlist = await self.get_playlist(prov_item_id)
            if playlist.is_editable:
                await self.api.api_delete(f"{CONTENT_TYPE_MUSIC}/playlist/{prov_item_id}")
                return True
        endpoint = self._library_endpoint(media_type, prov_item_id)
        if not endpoint:
            return False
        await self.api.api_delete(endpoint)
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
        await self._refresh_playlist_pages(prov_playlist_id)

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
            raise UnsupportedFeaturedException(
                "24six cannot remove the last track of a playlist, delete the playlist instead"
            )
        playlist_name = (await self._get_playlist_page(prov_playlist_id, 1)).get("title") or ""
        params: list[tuple[str, str]] = [("content[]", tid) for tid in remaining_ids]
        params.append(("force", "0"))
        params.append(("name", playlist_name))
        await self.api.api_patch(f"{CONTENT_TYPE_MUSIC}/playlist/{prov_playlist_id}", params=params)
        await self._refresh_playlist_pages(prov_playlist_id)

    @use_cache(3600 * 24, allow_expired_cache=True)
    async def get_similar_tracks(self, prov_track_id: str, limit: int = 25) -> list[Track]:
        """
        Get tracks that 24six recommends to play after the given track.

        :param prov_track_id: The provider track id.
        :param limit: Maximum number of tracks to return.
        """
        # the app's autoplay asks the AI-backed engine (ai=1) with the queue as seed; that
        # engine ignores the limit and answers with a fixed batch, so trim it here
        data = await self.api.api_post(
            f"{CONTENT_TYPE_MUSIC}/content/recommended",
            {"queue": [prov_track_id], "limit": limit, "ai": 1},
        )
        return [parse_track(self, item) for item in valid_items(data.get("data"))[:limit]]

    @use_cache(3600 * 24, allow_expired_cache=True)
    async def get_similar_artists(self, prov_artist_id: str, limit: int = 25) -> list[Artist]:
        """
        Get artists similar to the given artist.

        :param prov_artist_id: The provider artist id.
        :param limit: Maximum number of artists to return.
        """
        # the artist landing page carries the curated similar artists, fall back to the
        # similar-artist filter of the artist listing when it has none
        landing = await self._get_artist_data(prov_artist_id)
        similar = valid_items(landing.get("similar"))
        if not similar:
            data = await self.api.api_get(
                f"{CONTENT_TYPE_MUSIC}/artist",
                params={"similar_artist_id": prov_artist_id, "page": "1", "per_page": str(limit)},
            )
            similar = valid_items(data.get("data"))
        return [parse_artist(self, item) for item in similar[:limit]]

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Get the stream details for a track, podcast episode or radio station."""
        if media_type == MediaType.RADIO:
            endpoint = f"radio/{item_id}/play"
            params = {"livestream": "1", "format": HLS_AUDIO_FORMAT}
        else:
            content_type = (
                CONTENT_TYPE_PODCAST
                if media_type == MediaType.PODCAST_EPISODE
                else CONTENT_TYPE_MUSIC
            )
            endpoint = f"content/{item_id}/play"
            params = {"format": await self._preferred_audio_format(content_type, item_id)}
        # playback must not queue behind library/browse traffic: resolve the play URL
        # without the request throttle (the retries on transient errors still apply)
        async with self.api.throttler.bypass():
            stream_url = await self.api.api_get_stream_url(endpoint, params)
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
        Report a finished play to 24six.

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
        # an episode resumed mid-way was only listened to from its resume point
        started_at = self._resume_starts.pop(prov_item_id, 0)
        await self.api.log_playback(
            item_id=prov_item_id, seconds=max(position - started_at, 0), current=position
        )

    async def browse(self, path: str) -> Sequence[MediaItemType | ItemMapping | BrowseFolder]:
        """
        Browse this provider's items.

        :param path: The path to browse, (e.g. provider_id://artists).
        """
        prefix, _, subpath = path.partition("://")
        path_parts = subpath.split("/") if subpath else []
        folder = path_parts[0] if path_parts else None

        if folder == _FOLDER_CATEGORY and len(path_parts) > 1:
            return [
                parse_album(self, item) for item in await self._get_category_albums(path_parts[1])
            ]
        if folder == _FOLDER_CATEGORIES:
            return [
                BrowseFolder(
                    item_id=str(category["id"]),
                    provider=self.instance_id,
                    path=f"{prefix}://{_FOLDER_CATEGORY}/{category['id']}",
                    name=category.get("title") or "",
                )
                for category in await self._get_categories()
            ]
        if folder == _FOLDER_STORIES:
            return [parse_album(self, item) for item in await self._get_story_albums()]
        if folder == _FOLDER_RADIO:
            return [parse_radio(self, item) for item in await self._get_radio_stations()]

        result = list(await super().browse(path))
        if folder:
            return result
        # add the catalog folders to the root-level listing
        result.append(
            BrowseFolder(
                item_id=_FOLDER_CATEGORIES,
                provider=self.instance_id,
                path=f"{prefix}://{_FOLDER_CATEGORIES}",
                name="Categories",
                translation_key=_FOLDER_CATEGORIES,
            )
        )
        result.append(
            BrowseFolder(
                item_id=_FOLDER_STORIES,
                provider=self.instance_id,
                path=f"{prefix}://{_FOLDER_STORIES}",
                name="Stories",
                translation_key=_FOLDER_STORIES,
                is_playable=True,
            )
        )
        if self.api.profile_allows(ENTITY_RADIO):
            result.append(
                BrowseFolder(
                    item_id=_FOLDER_RADIO,
                    provider=self.instance_id,
                    path=f"{prefix}://{_FOLDER_RADIO}",
                    name="Radio stations",
                    translation_key=_FOLDER_RADIO,
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
            for row_id, row in RECOMMENDATION_ROWS.items()
            if self.api.profile_allows(row.permission)
        ]

    async def get_recommendation_items(
        self, item_id: str
    ) -> UniqueList[MediaItemType | ItemMapping | BrowseFolder]:
        """
        Get the items for a single recommendation row.

        :param item_id: The item_id of the row, as returned by get_recommendations.
        """
        items: UniqueList[MediaItemType | ItemMapping | BrowseFolder] = UniqueList()
        row = RECOMMENDATION_ROWS.get(item_id)
        if row is None:
            return items
        if row.dashboard_key:
            dashboard = await self._get_dashboard(row.content_type)
            if row.dashboard_key == "banners":
                return await self._resolve_banners(
                    valid_items(dashboard.get("banners"), key="entity_id")
                )
            entries = valid_items(dashboard.get(row.dashboard_key))
        else:
            entries = await self._get_listing_row(item_id)
        for entry in entries:
            if parsed := self._parse_by_type(entry, row.content_type):
                items.append(parsed)
        return items

    @use_cache(3600 * 24 * 30)
    async def _get_artist_data(self, prov_artist_id: str) -> dict[str, Any]:
        """Fetch and cache the raw artist landing page from the API."""
        return await self.api.api_get(f"{CONTENT_TYPE_MUSIC}/artist/{prov_artist_id}")

    @use_cache(3600 * 24 * 30, allow_expired_cache=True)
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
            raise MediaNotFoundError(f"Collection {prov_collection_id} not found")
        return collection_data

    @use_cache(3600 * 24 * 30)
    async def _get_cached_track_data(self, prov_track_id: str) -> dict[str, Any]:
        """Fetch and cache the raw track object from the API."""
        return await self._fetch_content(CONTENT_TYPE_MUSIC, prov_track_id)

    @use_cache(3600)
    async def _get_cached_episode_data(self, prov_episode_id: str) -> dict[str, Any]:
        """Fetch and briefly cache the raw episode object, which carries the resume state."""
        return await self._fetch_content(CONTENT_TYPE_PODCAST, prov_episode_id)

    async def _fetch_content(self, content_type: str, prov_content_id: str) -> dict[str, Any]:
        """Fetch the raw content (track or episode) object from the API."""
        data = await self.api.api_post(f"{content_type}/content/{prov_content_id}")
        content_data = data.get("content") or data
        if not content_data.get("id"):
            raise MediaNotFoundError(f"Content {prov_content_id} not found")
        return content_data

    @use_cache(3600 * 3, allow_expired_cache=True)
    async def _get_playlist_page(self, prov_playlist_id: str, api_page: int) -> dict[str, Any]:
        """Fetch and cache one page of a playlist landing page from the API."""
        data = await self.api.api_get(
            f"{CONTENT_TYPE_MUSIC}/playlist/{prov_playlist_id}", params={"page": str(api_page)}
        )
        playlist_data = data.get("playlist") or data
        if not playlist_data.get("id"):
            raise MediaNotFoundError(f"Playlist {prov_playlist_id} not found")
        return playlist_data

    async def _get_all_playlist_contents(self, prov_playlist_id: str) -> list[dict[str, Any]]:
        """Return the raw contents of a playlist across all of its pages."""
        contents: list[dict[str, Any]] = []
        api_page = 1
        while api_page <= MAX_PAGES:
            playlist_data = await self._get_playlist_page(prov_playlist_id, api_page)
            contents.extend(valid_items(playlist_data.get("contents")))
            pages = total_pages(playlist_data.get("pagination"))
            if pages is None or api_page >= pages:
                break
            api_page += 1
        return contents

    async def _refresh_playlist_pages(self, prov_playlist_id: str) -> None:
        """Fetch the pages of a playlist again after it was edited, replacing the cached ones."""
        async with self.mass.cache.handle_refresh(True):
            first_page = await self._get_playlist_page(prov_playlist_id, 1)
            for api_page in range(2, (total_pages(first_page.get("pagination")) or 1) + 1):
                await self._get_playlist_page(prov_playlist_id, api_page)

    @use_cache(3600, allow_expired_cache=True)
    async def _get_podcast_episode_items(self, prov_podcast_id: str) -> list[dict[str, Any]]:
        """Fetch and briefly cache the raw episodes of a podcast, newest first."""
        return [
            item
            async for item in self._paginate(
                f"{CONTENT_TYPE_PODCAST}/content",
                {"collection_id": prov_podcast_id, "sort": "newest", "no_pagination": "0"},
            )
        ]

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_listing_row(self, row_id: str) -> list[dict[str, Any]]:
        """Fetch and cache the raw items of a recommendation row served by a listing endpoint."""
        row = RECOMMENDATION_ROWS[row_id]
        data = await self.api.api_get(
            row.endpoint,
            params={**row.params, "page": "1", "per_page": str(RECOMMENDATION_ROW_SIZE)},
        )
        return valid_items(data.get("data"))[:RECOMMENDATION_ROW_SIZE]

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_dashboard(self, content_type: str) -> dict[str, Any]:
        """Fetch and cache the dashboard (home screen) payload of a content type."""
        return await self.api.api_get(content_type, params={"use_popularity_logic": "1"})

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_categories(self) -> list[dict[str, Any]]:
        """Fetch and cache the raw music categories."""
        return [
            item
            async for item in self._paginate(f"{CONTENT_TYPE_MUSIC}/category", {"sort": "popular"})
        ]

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_category_albums(self, category_id: str) -> list[dict[str, Any]]:
        """
        Fetch and cache the most popular albums of a category.

        :param category_id: The 24six category id.
        """
        return [
            item
            async for item in self._paginate(
                f"{CONTENT_TYPE_MUSIC}/collection",
                {"category_id": category_id, "sort": "popular", "with_contents": "0"},
                max_items=BROWSE_LIST_LIMIT,
            )
        ]

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_story_albums(self) -> list[dict[str, Any]]:
        """Fetch and cache the newest story albums."""
        return [
            item
            async for item in self._paginate(
                f"{CONTENT_TYPE_MUSIC}/collection", STORIES_PARAMS, max_items=BROWSE_LIST_LIMIT
            )
        ]

    @use_cache(3600 * 6, allow_expired_cache=True)
    async def _get_radio_stations(self) -> list[dict[str, Any]]:
        """Fetch and cache the radio stations from the live dashboard."""
        data = await self.api.api_get("live/dashboard", params={"use_popularity_logic": "1"})
        return radio_stations(data)

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
        except MusicAssistantError as err:
            # a failed refresh keeps the previous metadata, playback itself is unaffected
            self.logger.warning("Could not refresh the radio now-playing info: %s", err)
            return
        station = next(
            (
                item
                for item in radio_stations(data)
                if str(item.get("id")) == stream_details.item_id
            ),
            None,
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
        # refresh again right after the current song ends, instead of on a fixed timer
        remaining = now_playing.get("remaining")
        if isinstance(remaining, int | float) and remaining >= 0:
            stream_details.stream_metadata_update_interval = min(
                max(int(remaining) + 2, 5), RADIO_METADATA_MAX_INTERVAL
            )

    async def _preferred_audio_format(self, content_type: str, prov_content_id: str) -> str:
        """Return the stream format to request for a content item, as the app would."""
        if content_type == CONTENT_TYPE_PODCAST:
            content_data = await self._get_cached_episode_data(prov_content_id)
        else:
            content_data = await self._get_cached_track_data(prov_content_id)
        return get_audio_format(content_data) or DEFAULT_AUDIO_FORMAT

    async def _paginate(
        self, endpoint: str, params: dict[str, str], max_items: int | None = None
    ) -> AsyncGenerator[dict[str, Any]]:
        """
        Paginate a listing endpoint, yielding the items with a valid id.

        :param endpoint: The API endpoint to paginate.
        :param params: Extra query parameters (page is managed automatically, per_page
            defaults to PAGE_SIZE but can be overridden via params).
        :param max_items: Stop after (roughly) this many items instead of the last page.
        """
        page = 1
        yielded = 0
        while True:
            data = await self.api.api_get(
                endpoint, params={"per_page": str(PAGE_SIZE), **params, "page": str(page)}
            )
            items = valid_items(data.get("data"))
            pagination = (data.get("meta") or {}).get("pagination") or {}
            self.logger.debug(
                "Fetched %s items from %s page %s (pagination: %s)",
                len(items),
                endpoint,
                page,
                pagination or "none",
            )
            if not items:
                return
            for item in items:
                yield item
            yielded += len(items)
            if max_items is not None and yielded >= max_items:
                return
            if not has_next_page(pagination, page, len(items)):
                return
            if page >= MAX_PAGES:
                self.logger.warning(
                    "Stopped listing %s after %s pages, the remaining items are left out",
                    endpoint,
                    MAX_PAGES,
                )
                return
            page += 1

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
        if item_type == ENTITY_COLLECTION:
            if content_type == CONTENT_TYPE_PODCAST:
                return parse_podcast(self, item)
            return parse_album(self, item)
        if item_type == ENTITY_CONTENT:
            if content_type == CONTENT_TYPE_PODCAST and item.get("collection_id"):
                return parse_podcast_episode(self, item)
            return parse_track(self, item)
        if item_type == ENTITY_PLAYLIST:
            return parse_playlist(self, item)
        if item_type == ENTITY_ARTIST:
            return parse_artist(self, item)
        if item_type == ENTITY_RADIO:
            return parse_radio(self, item)
        return None

    async def _resolve_banners(
        self, banners: list[dict[str, Any]]
    ) -> UniqueList[MediaItemType | ItemMapping | BrowseFolder]:
        """
        Resolve homepage banners (entity references without titles) to their full items.

        :param banners: The raw banner objects of the dashboard.
        """
        getters = {
            ENTITY_PLAYLIST: self.get_playlist,
            ENTITY_COLLECTION: self.get_album,
            ENTITY_ARTIST: self.get_artist,
            ENTITY_CONTENT: self.get_track,
        }
        resolvable = [banner for banner in banners if banner.get("entity_type") in getters]
        # a handful of banners, each served from the (long-lived) item caches
        results = await asyncio.gather(
            *(getters[banner["entity_type"]](str(banner["entity_id"])) for banner in resolvable),
            return_exceptions=True,
        )
        items: UniqueList[MediaItemType | ItemMapping | BrowseFolder] = UniqueList()
        for banner, result in zip(resolvable, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "Could not resolve featured %s %s: %s",
                    banner["entity_type"],
                    banner["entity_id"],
                    result,
                )
                continue
            items.append(cast("MediaItemType", result))
        return items

    def _library_endpoint(self, media_type: MediaType, prov_item_id: str | None) -> str | None:
        """Return the library endpoint for an item, or None when unsupported."""
        if media_type == MediaType.ARTIST:
            # the artist library is derived from the saved albums and tracks: adding an
            # artist only marks it as favorite and removing it is not possible
            return None
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

    def _prov_item_id(self, item: MediaItemType) -> str | None:
        """Get the provider item id from a media item's provider mappings."""
        for mapping in item.provider_mappings:
            if mapping.provider_instance == self.instance_id:
                item_id: str = mapping.item_id
                return item_id
        return None
