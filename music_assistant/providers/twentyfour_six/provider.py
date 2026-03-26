"""24six music provider implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from music_assistant_models.enums import (
    ContentType,
    MediaType,
    StreamType,
)
from music_assistant_models.errors import (
    LoginFailed,
    MediaNotFoundError,
    ResourceTemporarilyUnavailable,
)
from music_assistant_models.media_items import (
    Album,
    Artist,
    AudioFormat,
    BrowseFolder,
    ItemMapping,
    MediaItemType,
    Playlist,
    RecommendationFolder,
    SearchResults,
    Track,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails

from music_assistant.controllers.cache import use_cache
from music_assistant.models.music_provider import MusicProvider

from .api_client import TwentyFourSixAPIClient
from .constants import CONF_DEVICE_ID, CONF_DEVICE_SERIAL, CONF_EMAIL, CONF_SESSION_DATA, MAX_PAGES
from .parsers import parse_album, parse_artist, parse_playlist, parse_track

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.enums import ProviderFeature
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant


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
        """Initialize 24six provider."""
        super().__init__(mass, manifest, config, supported_features)
        self.api = TwentyFourSixAPIClient(self)

    async def handle_async_init(self) -> None:
        """Handle async initialization of the provider."""
        if not self.config.get_value(CONF_EMAIL):
            msg = "Email is required"
            raise LoginFailed(msg)
        await self.api.ensure_logged_in()

    async def unload(self, is_removed: bool = False) -> None:
        """Handle unload/close of the provider."""
        if is_removed:
            self._update_config_value(CONF_SESSION_DATA, "")
        await self.api.close()

    def update_session_data(self, session_data: str) -> None:
        """Persist session data to the config store.

        :param session_data: JSON-encoded session data to store.
        """
        self._update_config_value(CONF_SESSION_DATA, session_data, encrypted=True)

    def update_device_id(self, device_id: str) -> None:
        """Persist device ID to the config store.

        :param device_id: Device identifier to store.
        """
        self._update_config_value(CONF_DEVICE_ID, device_id)

    def update_device_serial(self, device_serial: str) -> None:
        """Persist device serial to the config store.

        :param device_serial: Device serial identifier to store.
        """
        self._update_config_value(CONF_DEVICE_SERIAL, device_serial)

    @use_cache(3600)
    async def search(
        self,
        search_query: str,
        media_types: list[MediaType],
        limit: int = 5,
    ) -> SearchResults:
        """Perform search on 24six.

        :param search_query: Search query.
        :param media_types: A list of media_types to include.
        :param limit: Number of items to return in the search (per type).
        """
        data = await self.api.api_post("music/search", {"q": search_query, "limit": limit})

        artists: list[Artist | ItemMapping] = []
        albums: list[Album | ItemMapping] = []
        tracks: list[Track | ItemMapping] = []
        playlists: list[Playlist | ItemMapping] = []

        if MediaType.ARTIST in media_types:
            for item in (data.get("artists") or [])[:limit]:
                if item and item.get("id"):
                    artists.append(parse_artist(self, item))

        if MediaType.ALBUM in media_types:
            for item in (data.get("collections") or [])[:limit]:
                if item and item.get("id"):
                    albums.append(parse_album(self, item))

        if MediaType.TRACK in media_types:
            for item in (data.get("songs") or [])[:limit]:
                if item and item.get("id"):
                    tracks.append(parse_track(self, item))

        if MediaType.PLAYLIST in media_types:
            for item in (data.get("playlists") or [])[:limit]:
                if item and item.get("id"):
                    playlists.append(parse_playlist(self, item))

        return SearchResults(
            artists=artists,
            albums=albums,
            tracks=tracks,
            playlists=playlists,
        )

    # --- Shared cached API fetchers ---
    # These ensure that multiple methods needing the same API response
    # (e.g. get_album + get_album_tracks) share a single HTTP request.

    @use_cache(3600 * 24 * 30)
    async def _get_artist_data(self, prov_artist_id: str) -> dict[str, Any]:
        """Fetch and cache raw artist data from the API."""
        return await self.api.api_get(f"music/artist/{prov_artist_id}")

    @use_cache(3600 * 24 * 30)
    async def _get_collection_data(self, prov_album_id: str) -> dict[str, Any]:
        """Fetch and cache raw collection/album data from the API."""
        return await self.api.api_get(f"music/collection/{prov_album_id}")

    @use_cache(3600 * 3)
    async def _get_playlist_data(self, prov_playlist_id: str) -> dict[str, Any]:
        """Fetch and cache raw playlist data from the API."""
        return await self.api.api_get(f"music/playlist/{prov_playlist_id}")

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Get full artist details by id."""
        data = await self._get_artist_data(prov_artist_id)
        artist_data = data.get("artist", data)
        return parse_artist(self, artist_data)

    async def get_album(self, prov_album_id: str) -> Album:
        """Get full album details by id."""
        data = await self._get_collection_data(prov_album_id)
        collection_data = data.get("collection", data)
        if not collection_data:
            msg = f"Album {prov_album_id} not found"
            raise MediaNotFoundError(msg)
        return parse_album(self, collection_data)

    @use_cache(3600 * 24 * 30)
    async def get_track(self, prov_track_id: str) -> Track:
        """Get full track details by id."""
        data = await self.api.api_post(f"music/content/{prov_track_id}")
        return parse_track(self, data)

    async def get_playlist(self, prov_playlist_id: str) -> Playlist:
        """Get full playlist details by id."""
        data = await self._get_playlist_data(prov_playlist_id)
        playlist_data = data.get("playlist", data)
        if not playlist_data:
            msg = f"Playlist {prov_playlist_id} not found"
            raise MediaNotFoundError(msg)
        return parse_playlist(self, playlist_data)

    async def get_album_tracks(self, prov_album_id: str) -> list[Track]:
        """Get album tracks for given album id."""
        data = await self._get_collection_data(prov_album_id)
        collection_data = data.get("collection", data)
        album_artists: list[Artist] = []
        for artist_data in collection_data.get("artists", []):
            if artist_data and artist_data.get("id"):
                album_artists.append(parse_artist(self, artist_data))
        tracks: list[Track] = []
        for content in collection_data.get("contents", []):
            if content and content.get("id"):
                tracks.append(parse_track(self, content, fallback_artists=album_artists))
        return tracks

    async def get_artist_albums(self, prov_artist_id: str) -> list[Album]:
        """Get a list of all albums for the given artist."""
        albums: list[Album] = []
        async for item in self._paginate_library(
            "music/collection",
            {
                "artist_id": prov_artist_id,
                "sort": "popular",
                "use_popularity_logic": "1",
                "with_contents": "0",
            },
        ):
            albums.append(parse_album(self, item))
        return albums

    async def get_artist_toptracks(self, prov_artist_id: str) -> list[Track]:
        """Get a list of most popular tracks for the given artist."""
        tracks: list[Track] = []
        async for item in self._paginate_library(
            "music/content",
            {
                "artist_id": prov_artist_id,
                "no_pagination": "0",
                "sort": "popular",
            },
        ):
            tracks.append(parse_track(self, item))
        return tracks

    async def get_playlist_tracks(self, prov_playlist_id: str, page: int = 0) -> list[Track]:
        """Get playlist tracks for given playlist id."""
        if page > 0:
            return []
        data = await self._get_playlist_data(prov_playlist_id)
        playlist_data = data.get("playlist", data)
        tracks: list[Track] = []
        for idx, content in enumerate(playlist_data.get("contents") or [], start=1):
            if content and content.get("id"):
                track = parse_track(self, content)
                track.position = idx
                tracks.append(track)
        return tracks

    async def _paginate_library(
        self,
        endpoint: str,
        params: dict[str, str],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Paginate a library listing endpoint, yielding items with valid IDs.

        :param endpoint: The API endpoint to paginate.
        :param params: Extra query parameters (page is managed automatically,
            per_page defaults to 200 but can be overridden via params).
        """
        page = 1
        while page <= MAX_PAGES:
            data = await self.api.api_get(
                endpoint,
                params={"per_page": "200", **params, "page": str(page)},
            )
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                if item and item.get("id"):
                    yield item
            if not data.get("meta", {}).get("pagination", {}).get("next_page"):
                break
            page += 1

    async def get_library_artists(self) -> AsyncGenerator[Artist, None]:
        """Retrieve library artists from the provider."""
        async for item in self._paginate_library("music/artist", {"library": "1", "sort": "alpha"}):
            yield parse_artist(self, item)

    async def get_library_albums(self) -> AsyncGenerator[Album, None]:
        """Retrieve library albums from the provider."""
        async for item in self._paginate_library(
            "music/collection", {"library": "1", "sort": "alpha", "with_contents": "0"}
        ):
            yield parse_album(self, item)

    async def get_library_tracks(self) -> AsyncGenerator[Track, None]:
        """Retrieve library tracks from the provider."""
        async for item in self._paginate_library(
            "music/content", {"library": "1", "no_pagination": "0", "sort": "alpha"}
        ):
            yield parse_track(self, item)

    async def get_library_playlists(self) -> AsyncGenerator[Playlist, None]:
        """Retrieve library/subscribed playlists from the provider."""
        async for item in self._paginate_library(
            "music/playlist", {"library": "1", "sort": "alpha"}
        ):
            yield parse_playlist(self, item)

    async def library_add(self, item: MediaItemType) -> bool:
        """Add item to provider's library. Return true on success."""
        prov_item_id = self._get_prov_item_id(item)
        if not prov_item_id:
            return False
        api_type = self._media_type_to_api(item.media_type)
        if not api_type:
            return False
        try:
            await self.api.api_post(f"music/library/{api_type}/{prov_item_id}")
        except (MediaNotFoundError, ResourceTemporarilyUnavailable) as err:
            self.logger.debug("Failed to add %s to library: %s", prov_item_id, err)
            return False
        return True

    async def library_remove(self, prov_item_id: str, media_type: MediaType) -> bool:
        """Remove item from provider's library. Return true on success."""
        if media_type == MediaType.PLAYLIST:
            try:
                await self.api.api_delete(f"music/playlist/{prov_item_id}")
                return True
            except (MediaNotFoundError, ResourceTemporarilyUnavailable):
                pass
            # Fall back to library removal for non-owned playlists
        api_type = self._media_type_to_api(media_type)
        if not api_type:
            return False
        try:
            await self.api.api_delete(f"music/library/{api_type}/{prov_item_id}")
        except (MediaNotFoundError, ResourceTemporarilyUnavailable) as err:
            self.logger.debug("Failed to remove %s from library: %s", prov_item_id, err)
            return False
        return True

    async def set_favorite(self, prov_item_id: str, media_type: MediaType, favorite: bool) -> None:
        """Set favorite status for an item on 24six.

        :param prov_item_id: The provider item ID.
        :param media_type: The media type of the item.
        :param favorite: Whether to add or remove the favorite.
        """
        if media_type == MediaType.PLAYLIST:
            return
        api_type = self._media_type_to_api(media_type)
        if not api_type:
            return
        endpoint = f"music/{api_type}/{prov_item_id}/favorite"
        if favorite:
            await self.api.api_post(endpoint)
        else:
            await self.api.api_delete(endpoint)

    async def create_playlist(self, name: str, media_types: set[MediaType]) -> Playlist:
        """Create a new playlist on the provider."""
        data = await self.api.api_post("music/playlist", params={"name": name})
        playlist_data = data.get("playlist", data)
        return parse_playlist(self, playlist_data)

    async def add_playlist_tracks(self, prov_playlist_id: str, prov_track_ids: list[str]) -> None:
        """Add tracks to an existing playlist."""
        params: list[tuple[str, str]] = [("content[]", tid) for tid in prov_track_ids]
        params.append(("force", "0"))
        data = await self.api.api_post(f"music/playlist/{prov_playlist_id}/add", params=params)
        if data:
            await self._update_playlist_cache(prov_playlist_id, data)

    async def remove_playlist_tracks(
        self, prov_playlist_id: str, positions_to_remove: tuple[int, ...]
    ) -> None:
        """Remove tracks from a playlist by position.

        The 24six API has no endpoint to remove individual tracks. Instead,
        the full track list is replaced via PATCH with the remaining tracks.

        :param prov_playlist_id: The provider playlist ID.
        :param positions_to_remove: 1-based positions of tracks to remove.
        """
        data = await self.api.api_get(f"music/playlist/{prov_playlist_id}")
        playlist_data = data.get("playlist", data)
        playlist_name = playlist_data.get("title", "")
        contents = playlist_data.get("contents", [])
        remove_set = {int(p) for p in positions_to_remove}
        remaining_ids = [
            str(track["id"])
            for pos, track in enumerate(contents, start=1)
            if pos not in remove_set and track.get("id")
        ]
        params: list[tuple[str, str]] = [("content[]", tid) for tid in remaining_ids]
        params.append(("force", "0"))
        params.append(("name", playlist_name))
        result = await self.api.api_patch(f"music/playlist/{prov_playlist_id}", params=params)
        if result:
            await self._update_playlist_cache(prov_playlist_id, result)

    async def _update_playlist_cache(
        self, prov_playlist_id: str, playlist_data: dict[str, Any]
    ) -> None:
        """Optimistically update the cached playlist data from an API response.

        :param prov_playlist_id: The provider playlist ID.
        :param playlist_data: Raw playlist data returned by add/patch endpoints (unwrapped).
        """
        cache_key = f"_get_playlist_data.{prov_playlist_id}"
        wrapped = {"playlist": playlist_data}
        await self.mass.cache.set(
            key=cache_key,
            data=wrapped,
            expiration=3600 * 3,
            provider=self.instance_id,
        )

    @staticmethod
    def _media_type_to_api(media_type: MediaType) -> str | None:
        """Map MediaType to 24six API type string."""
        type_map: dict[MediaType, str] = {
            MediaType.ARTIST: "artist",
            MediaType.ALBUM: "collection",
            MediaType.TRACK: "content",
            MediaType.PLAYLIST: "playlist",
        }
        return type_map.get(media_type)

    def _get_prov_item_id(self, item: MediaItemType) -> str | None:
        """Get the provider item ID from a MediaItem."""
        for mapping in item.provider_mappings:
            if mapping.provider_instance == self.instance_id:
                item_id: str = mapping.item_id
                return item_id
        return None

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Get streamdetails for a track."""
        stream_url = await self.api.api_get_stream_url(item_id)

        is_hls = urlparse(stream_url).path.endswith(".m3u8")
        return StreamDetails(
            provider=self.instance_id,
            item_id=item_id,
            audio_format=AudioFormat(
                content_type=ContentType.AAC,
            ),
            media_type=media_type,
            stream_type=StreamType.HLS if is_hls else StreamType.HTTP,
            allow_seek=True,
            can_seek=True,
            path=stream_url,
        )

    # --- Playback reporting ---

    async def on_played(
        self,
        media_type: MediaType,
        prov_item_id: str,
        fully_played: bool,
        position: int,
        media_item: MediaItemType,
        is_playing: bool = False,
    ) -> None:
        """Report playback progress to 24six.

        :param media_type: The media type that is played.
        :param prov_item_id: The provider item ID.
        :param fully_played: Whether the track has been fully played.
        :param position: The current position in seconds.
        :param media_item: The full media item details.
        :param is_playing: Whether the track is currently playing.
        """
        if media_type != MediaType.TRACK:
            return
        # MA callback provides position only; use it for both seconds (total
        # listen time) and current (playback position) since they're equivalent here.
        await self.api.log_playback(
            item_id=prov_item_id,
            seconds=position,
            current=position,
        )

    # Dedicated v3 API endpoints for recommendation sections.
    # Each tuple: (section_id, display_name, endpoint, params)
    _RECOMMENDATION_SECTIONS: tuple[tuple[str, str, str, dict[str, str]], ...] = (
        (
            "newAlbums",
            "New Albums",
            "music/collection",
            {"sort": "newAlbums", "page": "1", "per_page": "20", "with_contents": "0"},
        ),
        (
            "newSingles",
            "New Singles",
            "music/collection",
            {"sort": "newSingles", "page": "1", "per_page": "20", "with_contents": "0"},
        ),
        (
            "playlists",
            "24Six Playlists",
            "music/playlist",
            {"public": "1", "sort": "popular", "page": "1", "per_page": "20"},
        ),
        (
            "artists",
            "Popular Artists",
            "music/artist",
            {"sort": "popular", "page": "1", "per_page": "20"},
        ),
        (
            "newArtists",
            "New Artists",
            "music/artist",
            {"sort": "recent", "page": "1", "per_page": "20"},
        ),
        (
            "trending",
            "Trending Tracks",
            "music/content",
            {"sort": "popular", "no_pagination": "0", "page": "1", "per_page": "20"},
        ),
    )

    @use_cache(3600 * 6)
    async def recommendations(self) -> list[RecommendationFolder]:
        """Get this provider's recommendations from multiple v3 API endpoints."""
        folders: list[RecommendationFolder] = []

        try:
            homepage = await self.api.api_get("music", params={"use_popularity_logic": "1"})
        except (LoginFailed, MediaNotFoundError, ResourceTemporarilyUnavailable) as err:
            self.logger.debug("Failed to fetch homepage: %s", err)
            homepage = {}

        # Featured banners (entity references to playlists/collections)
        if banners := homepage.get("banners"):
            banner_items: UniqueList[MediaItemType | ItemMapping | BrowseFolder] = UniqueList()
            for banner in banners:
                item = await self._resolve_banner(banner)
                if item:
                    banner_items.append(item)
            if banner_items:
                folders.append(
                    RecommendationFolder(
                        item_id="banners",
                        name="Featured",
                        provider=self.instance_id,
                        path=f"{self.instance_id}://recommendations/banners",
                        items=banner_items,
                    )
                )

        # 24Six Presents (curated content from homepage)
        if by24six := homepage.get("by24Six"):
            by24six_items: UniqueList[MediaItemType | ItemMapping | BrowseFolder] = UniqueList()
            for item in by24six:
                parsed = self._parse_by_type(item)
                if parsed:
                    by24six_items.append(parsed)
            await self._enrich_tracks_duration(by24six_items)
            if by24six_items:
                folders.append(
                    RecommendationFolder(
                        item_id="by24Six",
                        name="24Six Presents",
                        provider=self.instance_id,
                        path=f"{self.instance_id}://recommendations/by24Six",
                        items=by24six_items,
                    )
                )

        # Dedicated endpoint sections
        for section_id, display_name, endpoint, params in self._RECOMMENDATION_SECTIONS:
            try:
                data = await self.api.api_get(endpoint, params=params)
            except (LoginFailed, MediaNotFoundError, ResourceTemporarilyUnavailable) as err:
                self.logger.debug("Failed to fetch %s: %s", section_id, err)
                continue
            items_list = data.get("data", [])[:20]
            if not items_list:
                continue
            items: UniqueList[MediaItemType | ItemMapping | BrowseFolder] = UniqueList()
            for item in items_list:
                parsed = self._parse_by_type(item)
                if parsed:
                    items.append(parsed)
            await self._enrich_tracks_duration(items)
            if items:
                folders.append(
                    RecommendationFolder(
                        item_id=section_id,
                        name=display_name,
                        provider=self.instance_id,
                        path=f"{self.instance_id}://recommendations/{section_id}",
                        items=items,
                    )
                )

        return folders

    async def _enrich_tracks_duration(
        self,
        items: UniqueList[MediaItemType | ItemMapping | BrowseFolder],
    ) -> None:
        """Enrich tracks missing duration by fetching full details in parallel."""
        indices: list[int] = []
        tasks: list[asyncio.Task[Track]] = []
        for i, item in enumerate(items):
            if isinstance(item, Track) and not item.duration:
                indices.append(i)
                tasks.append(asyncio.create_task(self.get_track(item.item_id)))
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for idx, result in zip(indices, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.debug(
                    "Failed to enrich track %s duration: %s",
                    items[idx].item_id,
                    result,
                )
                continue
            items[idx] = result

    def _parse_by_type(self, item: dict[str, Any]) -> MediaItemType | None:
        """Parse a v3 API item to the appropriate media type based on its type field."""
        if not item or not item.get("id"):
            return None
        item_type = item.get("type", "")
        if item_type == "collection":
            return parse_album(self, item)
        if item_type == "content":
            return parse_track(self, item)
        if item_type == "playlist":
            return parse_playlist(self, item)
        if item_type == "artist":
            return parse_artist(self, item)
        return None

    async def _resolve_banner(self, banner: dict[str, Any]) -> MediaItemType | None:
        """Resolve a homepage banner to its full media item."""
        entity_id = banner.get("entity_id")
        if not entity_id:
            return None
        entity_type = banner.get("entity_type", "")
        entity_id_str = str(entity_id)
        try:
            if entity_type == "playlist":
                return await self.get_playlist(entity_id_str)
            if entity_type == "collection":
                return await self.get_album(entity_id_str)
            if entity_type == "artist":
                return await self.get_artist(entity_id_str)
            if entity_type == "content":
                return await self.get_track(entity_id_str)
        except (MediaNotFoundError, LoginFailed, ResourceTemporarilyUnavailable):
            return None
        return None

    async def _browse_recommendation_section(
        self,
        endpoint: str,
        base_params: dict[str, str],
    ) -> list[MediaItemType | ItemMapping | BrowseFolder]:
        """Fetch all pages of a recommendation section for drill-down browsing.

        :param endpoint: The API endpoint to paginate.
        :param base_params: Base query parameters from the section definition.
        """
        items: UniqueList[MediaItemType | ItemMapping | BrowseFolder] = UniqueList()
        page = 1
        while page <= MAX_PAGES and len(items) < 200:
            params = {**base_params, "page": str(page), "per_page": "200"}
            data = await self.api.api_get(endpoint, params=params)
            page_items = data.get("data", [])
            if not page_items:
                break
            for item in page_items:
                parsed = self._parse_by_type(item)
                if parsed:
                    items.append(parsed)
            if not data.get("meta", {}).get("pagination", {}).get("next_page"):
                break
            page += 1
        await self._enrich_tracks_duration(items)
        return list(items)

    async def browse(self, path: str) -> Sequence[MediaItemType | ItemMapping | BrowseFolder]:
        """Browse this provider's items.

        :param path: The path to browse, (e.g. provider_id://artists).
        """
        path_parts = path.split("://", maxsplit=1)[1].split("/") if "://" in path else []
        subpath = path_parts[0] if path_parts else None

        if subpath == "category" and len(path_parts) > 1:
            category_id = path_parts[1]
            data = await self.api.api_get(f"music/category/{category_id}")
            result: list[MediaItemType | ItemMapping | BrowseFolder] = []
            for collection in data.get("releases", []):
                if collection and collection.get("id"):
                    result.append(parse_album(self, collection))
            return result

        if subpath == "categories":
            data = await self.api.api_get(
                "music/category",
                params={"page": "1", "per_page": "100", "sort": "popular"},
            )
            categories = data.get("data", [])
            folders: list[BrowseFolder] = []
            for cat in categories:
                cat_id = cat.get("id")
                if not cat_id:
                    continue
                folders.append(
                    BrowseFolder(
                        item_id=str(cat_id),
                        provider=self.instance_id,
                        path=f"{path.split('://', maxsplit=1)[0]}://category/{cat_id}",
                        name=cat.get("title", ""),
                    )
                )
            return folders

        if subpath == "recommendations" and len(path_parts) > 1:
            section_id = path_parts[1]
            for sid, _, endpoint, params in self._RECOMMENDATION_SECTIONS:
                if sid == section_id:
                    return await self._browse_recommendation_section(endpoint, params)

        result = list(await super().browse(path))
        # Only add the Categories folder to the root-level browse listing
        if not subpath:
            result.append(
                BrowseFolder(
                    item_id="categories",
                    provider=self.instance_id,
                    path=f"{path.split('://', maxsplit=1)[0]}://categories",
                    name="Categories",
                )
            )
        return result
