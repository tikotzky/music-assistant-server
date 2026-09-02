"""Tests for the 24six provider implementation."""

from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from music_assistant_models.enums import MediaType, ProviderFeature, StreamType
from music_assistant_models.errors import MediaNotFoundError, UnsupportedFeaturedException
from music_assistant_models.media_items import (
    Album,
    Artist,
    BrowseFolder,
    Playlist,
    Podcast,
    ProviderMapping,
    Radio,
    Track,
)

from music_assistant.models.music_provider import MusicProvider
from music_assistant.providers.twentyfour_six import SUPPORTED_FEATURES
from music_assistant.providers.twentyfour_six.helpers import has_next_page, total_pages
from music_assistant.providers.twentyfour_six.provider import TwentyFourSixProvider

PLAYLIST_PAGE_1: dict[str, Any] = {
    "playlist": {
        "id": 44,
        "title": "Big Playlist",
        "mine": True,
        "contents": [{"id": 1, "title": "One"}, {"id": 2, "title": "Two"}],
        "pagination": {"total": 3, "per_page": 2, "current_page": 1, "next_page": 2},
    }
}
PLAYLIST_PAGE_2: dict[str, Any] = {
    "playlist": {
        "id": 44,
        "title": "Big Playlist",
        "mine": True,
        "contents": [{"id": 3, "title": "Three"}],
        "pagination": {"total": 3, "per_page": 2, "current_page": 2, "next_page": None},
    }
}
LAST_PAGE_META: dict[str, Any] = {"meta": {"pagination": {"next_page": None}}}


def _api_get(provider: TwentyFourSixProvider) -> AsyncMock:
    return cast("AsyncMock", provider.api.api_get)


def _api_post(provider: TwentyFourSixProvider) -> AsyncMock:
    return cast("AsyncMock", provider.api.api_post)


def _api_delete(provider: TwentyFourSixProvider) -> AsyncMock:
    return cast("AsyncMock", provider.api.api_delete)


def _mapping(provider: TwentyFourSixProvider, item_id: str) -> ProviderMapping:
    return ProviderMapping(
        item_id=item_id,
        provider_domain=provider.domain,
        provider_instance=provider.instance_id,
    )


def _radio(provider: TwentyFourSixProvider) -> Radio:
    return Radio(
        item_id="77",
        provider=provider.instance_id,
        name="Radio",
        provider_mappings={_mapping(provider, "77")},
    )


def _playlist_pages(endpoint: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
    assert endpoint == "music/playlist/44"
    return PLAYLIST_PAGE_2 if (params or {}).get("page") == "2" else PLAYLIST_PAGE_1


def test_radio_is_served_but_not_synced(provider: TwentyFourSixProvider) -> None:
    """Radio stations are playable and searchable, yet never added to the library."""
    assert MediaType.RADIO in provider.supported_media_types
    assert ProviderFeature.LIBRARY_RADIOS not in SUPPORTED_FEATURES
    assert TwentyFourSixProvider.get_library_radios is MusicProvider.get_library_radios


async def test_search_maps_result_keys(provider: TwentyFourSixProvider) -> None:
    """Search reads every result list and skips empty queries the API would reject."""
    _api_post(provider).return_value = {
        "artists": [{"id": 1, "name": "A"}],
        "collections": [{"id": 2, "title": "B"}],
        "content": [{"id": 3, "title": "C"}, None],
        "playlists": [{"id": 4, "title": "D"}],
    }
    results = await provider.search(
        "query", [MediaType.ARTIST, MediaType.ALBUM, MediaType.TRACK, MediaType.PLAYLIST], 5
    )
    _api_post(provider).assert_awaited_once_with("music/search", {"q": "query", "limit": 5})
    assert [item.item_id for item in results.artists] == ["1"]
    assert [item.item_id for item in results.albums] == ["2"]
    assert [item.item_id for item in results.tracks] == ["3"]
    assert [item.item_id for item in results.playlists] == ["4"]

    _api_post(provider).reset_mock()
    assert (await provider.search("   ", [MediaType.TRACK], 5)).tracks == []
    _api_post(provider).assert_not_awaited()


async def test_search_skips_podcasts_when_profile_disallows(
    provider: TwentyFourSixProvider,
) -> None:
    """A profile without podcast access never queries the podcast catalog."""
    provider.api.profile = {"allowed": {"podcast": False}}
    _api_post(provider).return_value = {"collections": [{"id": 9, "title": "Show"}]}
    results = await provider.search("query", [MediaType.PODCAST], 5)
    assert results.podcasts == []
    _api_post(provider).assert_not_awaited()

    provider.api.profile = {"allowed": {"podcast": True}}
    results = await provider.search("query", [MediaType.PODCAST], 5)
    _api_post(provider).assert_awaited_once_with("podcast/search", {"q": "query", "limit": 5})
    assert isinstance(results.podcasts[0], Podcast)


async def test_playlist_tracks_are_paged(provider: TwentyFourSixProvider) -> None:
    """Playlist tracks come one API page at a time with running positions."""
    _api_get(provider).side_effect = _playlist_pages
    first = await provider.get_playlist_tracks("44", page=0)
    assert [(track.item_id, track.position) for track in first] == [("1", 1), ("2", 2)]
    second = await provider.get_playlist_tracks("44", page=1)
    assert [(track.item_id, track.position) for track in second] == [("3", 3)]

    _api_get(provider).reset_mock()
    assert await provider.get_playlist_tracks("44", page=2) == []
    # only the first page is consulted to learn the page count, page 3 is never requested
    assert [call.kwargs["params"]["page"] for call in _api_get(provider).await_args_list] == ["1"]


async def test_playlist_edits_replace_and_refresh(provider: TwentyFourSixProvider) -> None:
    """Removing tracks rewrites the remaining ones across pages and re-reads the playlist."""
    _api_get(provider).side_effect = _playlist_pages
    await provider.remove_playlist_tracks("44", (2,))
    cast("AsyncMock", provider.api.api_patch).assert_awaited_once_with(
        "music/playlist/44",
        params=[("content[]", "1"), ("content[]", "3"), ("force", "0"), ("name", "Big Playlist")],
    )
    # both pages are fetched again after the edit so the cache holds the new contents
    refreshed = [c.kwargs["params"]["page"] for c in _api_get(provider).await_args_list[-2:]]
    assert refreshed == ["1", "2"]

    _api_get(provider).reset_mock()
    await provider.add_playlist_tracks("44", ["5"])
    _api_post(provider).assert_awaited_once_with(
        "music/playlist/44/add", params=[("content[]", "5"), ("force", "0")]
    )
    assert _api_get(provider).await_count == 2


async def test_remove_last_playlist_track_is_refused(provider: TwentyFourSixProvider) -> None:
    """The API cannot empty a playlist, so removing the last track raises instead of no-op."""
    _api_get(provider).return_value = {
        "playlist": {"id": 44, "title": "One", "contents": [{"id": 1}], "pagination": {}}
    }
    with pytest.raises(UnsupportedFeaturedException):
        await provider.remove_playlist_tracks("44", (1,))
    cast("AsyncMock", provider.api.api_patch).assert_not_awaited()


async def test_stream_details_use_content_audio_format(provider: TwentyFourSixProvider) -> None:
    """The stream is requested in the format the content declares, HLS is detected."""
    _api_post(provider).return_value = {"id": 33, "title": "T", "audio_format": "mp3"}
    stream_url = cast("AsyncMock", provider.api.api_get_stream_url)
    stream_url.return_value = "https://cdn.example.com/track.mp3"
    details = await provider.get_stream_details("33", MediaType.TRACK)
    stream_url.assert_awaited_once_with("content/33/play", {"format": "mp3"})
    assert details.stream_type == StreamType.HTTP
    assert details.path == "https://cdn.example.com/track.mp3"
    assert details.can_seek is True
    assert details.stream_metadata_update_callback is None

    _api_post(provider).return_value = {"id": 34, "title": "T"}
    stream_url.return_value = "https://stream.mux.com/abc.m3u8?token=1"
    details = await provider.get_stream_details("34", MediaType.PODCAST_EPISODE)
    stream_url.assert_awaited_with("content/34/play", {"format": "m4a"})
    assert details.stream_type == StreamType.HLS
    assert _api_post(provider).await_args_list[-1].args[0] == "podcast/content/34"


async def test_stream_details_for_radio(provider: TwentyFourSixProvider) -> None:
    """A radio station streams its live HLS feed, cannot seek and refreshes now-playing."""
    stream_url = cast("AsyncMock", provider.api.api_get_stream_url)
    stream_url.return_value = "https://live.example.com/radio/index.m3u8"
    details = await provider.get_stream_details("77", MediaType.RADIO)
    stream_url.assert_awaited_once_with("radio/77/play", {"livestream": "1", "format": "m3u8"})
    assert details.stream_type == StreamType.HLS
    assert details.can_seek is False
    assert details.stream_metadata_update_callback is not None
    assert details.stream_metadata_update_interval == 20
    _api_post(provider).assert_not_awaited()

    _api_get(provider).return_value = {
        "audio": {
            "radio": [
                {"id": 78, "title": "Other", "radio_now": {"title": "Nope"}},
                {
                    "id": 77,
                    "title": "Station",
                    "radio_now": {
                        "title": "Song",
                        "subtitle": "Singer",
                        "album": "Record",
                        "img": "https://img.example.com/now.jpg",
                        "duration": 200,
                        "elapsed": 42,
                        "remaining": 158,
                    },
                },
            ]
        }
    }
    await details.stream_metadata_update_callback(details, 0)
    assert details.stream_metadata is not None
    assert details.stream_metadata.title == "Song"
    assert details.stream_metadata.artist == "Singer"
    assert details.stream_metadata.album == "Record"
    assert details.stream_metadata.image_url == "https://img.example.com/now.jpg"
    assert details.stream_metadata.duration == 200
    assert details.stream_metadata.elapsed_time == 42
    # the next refresh is scheduled right after the current song ends
    assert details.stream_metadata_update_interval == 160
    _api_get(provider).assert_awaited_once_with(
        "live/dashboard", params={"use_popularity_logic": "1"}
    )

    # a station without now-playing info keeps the previous metadata
    _api_get(provider).return_value = {"audio": {"radio": [{"id": 77, "radio_now": None}]}}
    await details.stream_metadata_update_callback(details, 30)
    assert details.stream_metadata.title == "Song"


async def test_artist_listings(provider: TwentyFourSixProvider) -> None:
    """Top tracks are one page, all tracks are paginated, top albums come from the landing."""
    _api_get(provider).return_value = {"data": [{"id": 1, "title": "Hit", "length": 90}]}
    tracks = await provider.get_artist_toptracks("11")
    _api_get(provider).assert_awaited_once_with(
        "music/content",
        params={
            "artist_id": "11",
            "no_pagination": "0",
            "sort": "popular",
            "page": "1",
            "per_page": "50",
        },
    )
    assert [track.item_id for track in tracks] == ["1"]

    _api_get(provider).reset_mock()
    _api_get(provider).return_value = {"data": [{"id": 2, "title": "All"}], **LAST_PAGE_META}
    tracks = await provider.get_artist_tracks("11")
    assert cast("Any", _api_get(provider).await_args).kwargs["params"]["sort"] == "alpha"
    assert [track.item_id for track in tracks] == ["2"]

    _api_get(provider).reset_mock()
    _api_get(provider).return_value = {"artist": {"id": 11}, "albums": [{"id": 3, "title": "Top"}]}
    albums = await provider.get_artist_topalbums("11")
    _api_get(provider).assert_awaited_once_with("music/artist/11")
    assert [album.item_id for album in albums] == ["3"]


async def test_similar_tracks_and_artists(provider: TwentyFourSixProvider) -> None:
    """Similar tracks use the app's autoplay endpoint, similar artists the artist landing."""
    _api_post(provider).return_value = {"data": [{"id": 8, "title": "Next", "type": "content"}]}
    tracks = await provider.get_similar_tracks("42", limit=10)
    _api_post(provider).assert_awaited_once_with(
        "music/content/recommended", {"queue": ["42"], "limit": 10, "ai": 0}
    )
    assert [track.item_id for track in tracks] == ["8"]

    # the artist landing page has no similar artists: fall back to the listing filter
    async def api_get(endpoint: str, **_kwargs: Any) -> dict[str, Any]:
        if endpoint == "music/artist/11":
            return {"artist": {"id": 11, "name": "A"}, "similar": None}
        return {"data": [{"id": 9, "name": "Alike"}]}

    _api_get(provider).side_effect = api_get
    artists = await provider.get_similar_artists("11", limit=7)
    _api_get(provider).assert_awaited_with(
        "music/artist", params={"similar_artist_id": "11", "page": "1", "per_page": "7"}
    )
    assert [artist.item_id for artist in artists] == ["9"]

    # the landing page's curated list wins when present
    _api_get(provider).side_effect = None
    _api_get(provider).return_value = {"artist": {"id": 11}, "similar": [{"id": 12, "name": "B"}]}
    _api_get(provider).reset_mock()
    artists = await provider.get_similar_artists("11", limit=7)
    _api_get(provider).assert_awaited_once_with("music/artist/11")
    assert [artist.item_id for artist in artists] == ["12"]


async def test_create_playlist_is_editable(provider: TwentyFourSixProvider) -> None:
    """A playlist we created is editable even though the create response omits ownership."""
    _api_post(provider).return_value = {"playlist": {"id": 77, "title": "Mine"}}
    playlist = await provider.create_playlist("Mine", {MediaType.TRACK})
    _api_post(provider).assert_awaited_once_with("music/playlist", params={"name": "Mine"})
    assert playlist.is_editable is True
    assert next(iter(playlist.provider_mappings)).is_unique is True


async def test_recommendation_rows_and_items(provider: TwentyFourSixProvider) -> None:
    """Rows have stable ids and their items come from the dashboards or a listing."""
    rows = await provider.get_recommendations()
    row_ids = [row.item_id for row in rows]
    assert row_ids[:2] == ["banners", "by24Six"]
    assert {"newAlbums", "newStories", "trending", "recent", "newPodcasts"} <= set(row_ids)
    assert {"continueListening", "popularPodcasts", "trendingEpisodes"} <= set(row_ids)
    assert all(row.items == [] for row in rows)
    assert all(row.translation_key for row in rows)

    # podcast rows are left out for a profile that may not access podcasts
    provider.api.profile = {"allowed": {"podcast": False, "music": True}}
    row_ids = [row.item_id for row in await provider.get_recommendations()]
    assert "newPodcasts" not in row_ids
    assert "continueListening" not in row_ids
    assert {"newAlbums", "newStories"} <= set(row_ids)
    provider.api.profile = {}

    # music dashboard rows come from the single (cached) dashboard payload
    _api_get(provider).return_value = {
        "newAlbums": [
            {"id": 1, "type": "collection", "title": "Album"},
            {"id": 2, "type": "artist", "name": "Artist"},
            {"id": 3, "type": "playlist", "title": "List"},
            {"id": 4, "type": "content", "title": "Song", "length": 100},
            {"id": 5, "type": "unknown"},
        ]
    }
    items = await provider.get_recommendation_items("newAlbums")
    _api_get(provider).assert_awaited_once_with("music", params={"use_popularity_logic": "1"})
    assert [type(item) for item in items] == [Album, Artist, Playlist, Track]

    # listing rows use their own endpoint
    _api_get(provider).reset_mock()
    _api_get(provider).return_value = {
        "data": [{"id": 6, "type": "content", "content_type": "podcast", "collection_id": 9}]
    }
    items = await provider.get_recommendation_items("newPodcasts")
    _api_get(provider).assert_awaited_once_with(
        "podcast/content",
        params={"sort": "newest", "no_pagination": "0", "page": "1", "per_page": "50"},
    )
    assert [type(item).__name__ for item in items] == ["PodcastEpisode"]

    # podcast dashboard rows come from the podcast dashboard and parse as podcast items
    _api_get(provider).reset_mock()
    _api_get(provider).return_value = {
        "popular": [{"id": 7, "type": "collection", "title": "Show"}],
        "trending": [{"id": 8, "type": "content", "collection_id": 7, "title": "Ep"}],
    }
    shows = await provider.get_recommendation_items("popularPodcasts")
    _api_get(provider).assert_awaited_once_with("podcast", params={"use_popularity_logic": "1"})
    assert [type(item).__name__ for item in shows] == ["Podcast"]
    episodes = await provider.get_recommendation_items("trendingEpisodes")
    assert [type(item).__name__ for item in episodes] == ["PodcastEpisode"]
    assert await provider.get_recommendation_items("nope") == []


async def test_recommendation_banners_resolve_entities(
    provider: TwentyFourSixProvider, caplog: pytest.LogCaptureFixture
) -> None:
    """Featured banners resolve to their full items; a stale one is logged and skipped."""

    async def api_get(endpoint: str, **_kwargs: Any) -> dict[str, Any]:
        if endpoint == "music":
            return {
                "banners": [
                    {"entity_id": 44, "entity_type": "playlist"},
                    {"entity_id": 22, "entity_type": "collection"},
                    {"entity_id": 99, "entity_type": "artist"},
                    {"entity_id": None, "entity_type": "collection"},
                    {"entity_id": 5, "entity_type": "poll"},
                ]
            }
        if endpoint == "music/playlist/44":
            return {"playlist": {"id": 44, "title": "Featured list"}}
        if endpoint == "music/collection/22":
            return {"collection": {"id": 22, "title": "Featured album"}}
        raise MediaNotFoundError(f"{endpoint} not found")

    _api_get(provider).side_effect = api_get
    with caplog.at_level(logging.WARNING):
        items = await provider.get_recommendation_items("banners")
    assert [(type(item), item.item_id) for item in items] == [(Playlist, "44"), (Album, "22")]
    assert "Could not resolve featured artist 99" in caplog.text


async def test_library_endpoints_per_media_type(provider: TwentyFourSixProvider) -> None:
    """Library and favorite calls target the content type matching the media type."""
    podcast = Podcast(
        item_id="55",
        provider=provider.instance_id,
        name="Show",
        provider_mappings={_mapping(provider, "55")},
    )
    assert await provider.library_add(podcast) is True
    _api_post(provider).assert_awaited_once_with("podcast/library/collection/55")

    assert await provider.library_remove("33", MediaType.TRACK) is True
    _api_delete(provider).assert_awaited_once_with("music/library/content/33")

    await provider.set_favorite("55", MediaType.PODCAST, True)
    assert _api_post(provider).await_args_list[-1].args == ("podcast/collection/55/favorite",)
    await provider.set_favorite("44", MediaType.PLAYLIST, True)
    assert _api_post(provider).await_count == 2

    assert await provider.library_add(_radio(provider)) is False
    # artists cannot be added to or removed from the 24six library, only favorited
    artist = Artist(
        item_id="11",
        provider=provider.instance_id,
        name="A",
        provider_mappings={_mapping(provider, "11")},
    )
    assert await provider.library_add(artist) is False
    assert await provider.library_remove("11", MediaType.ARTIST) is False
    await provider.set_favorite("11", MediaType.ARTIST, False)
    _api_delete(provider).assert_awaited_with("music/artist/11/favorite")


async def test_playlist_removal_depends_on_ownership(provider: TwentyFourSixProvider) -> None:
    """An owned playlist is deleted, a followed one is only removed from the library."""
    _api_get(provider).return_value = {"playlist": {"id": 44, "title": "Mine", "mine": True}}
    assert await provider.library_remove("44", MediaType.PLAYLIST) is True
    _api_delete(provider).assert_awaited_once_with("music/playlist/44")

    _api_delete(provider).reset_mock()
    _api_get(provider).return_value = {"playlist": {"id": 45, "title": "Theirs", "mine": False}}
    assert await provider.library_remove("45", MediaType.PLAYLIST) is True
    _api_delete(provider).assert_awaited_once_with("music/library/playlist/45")


async def test_browse_root_and_catalog_folders(provider: TwentyFourSixProvider) -> None:
    """The root lists the catalog folders next to the library ones, radio when allowed."""
    music = cast("Any", provider.mass).music
    for controller in ("artists", "albums", "tracks", "playlists", "podcasts"):
        getattr(music, controller).library_items = AsyncMock(return_value=[])
    root = cast("list[BrowseFolder]", await provider.browse("twentyfour_six--test://"))
    assert [folder.item_id for folder in root][-3:] == ["categories", "stories", "radio"]
    assert "radios" not in [folder.item_id for folder in root]
    provider.api.profile = {"allowed": {"radio": False}}
    root = cast("list[BrowseFolder]", await provider.browse("twentyfour_six--test://"))
    assert "radio" not in [folder.item_id for folder in root]
    provider.api.profile = {}

    _api_get(provider).return_value = {
        "data": [{"id": 3, "title": "Wedding"}, {"title": "x"}],
        **LAST_PAGE_META,
    }
    folders = cast("list[BrowseFolder]", await provider.browse("twentyfour_six--test://categories"))
    assert cast("Any", _api_get(provider).await_args).args[0] == "music/category"
    assert [(folder.item_id, folder.name, folder.path) for folder in folders] == [
        ("3", "Wedding", "twentyfour_six--test://category/3")
    ]

    _api_get(provider).reset_mock()
    _api_get(provider).return_value = {"data": [{"id": 22, "title": "Album"}], **LAST_PAGE_META}
    albums = await provider.browse("twentyfour_six--test://category/3")
    assert cast("Any", _api_get(provider).await_args).kwargs["params"]["category_id"] == "3"
    assert [item.item_id for item in albums] == ["22"]

    _api_get(provider).reset_mock()
    _api_get(provider).return_value = {
        "data": [
            {"id": 5, "type": "collection", "title": "Bedtime Tales", "contents": [{"id": 1}]}
        ],
        **LAST_PAGE_META,
    }
    stories = await provider.browse("twentyfour_six--test://stories")
    assert cast("Any", _api_get(provider).await_args).kwargs["params"]["sort"] == "newStories"
    assert [(type(item), item.item_id) for item in stories] == [(Album, "5")]

    _api_get(provider).reset_mock()
    _api_get(provider).return_value = {"audio": {"radio": [{"id": 77, "title": "Station"}]}}
    radios = await provider.browse("twentyfour_six--test://radio")
    _api_get(provider).assert_awaited_once_with(
        "live/dashboard", params={"use_popularity_logic": "1"}
    )
    assert [(type(item), item.name) for item in radios] == [(Radio, "Station")]
    assert (await provider.get_radio("77")).item_id == "77"
    with pytest.raises(MediaNotFoundError):
        await provider.get_radio("1")


async def test_podcast_episodes_ranked_by_date(provider: TwentyFourSixProvider) -> None:
    """Episodes are listed newest-first by the API and positioned oldest-to-newest."""

    async def api_get(endpoint: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        if endpoint == "podcast/collection/55":
            return {"collection": {"id": 55, "title": "Show"}}
        assert endpoint == "podcast/content"
        assert (params or {})["collection_id"] == "55"
        return {
            "data": [
                {"id": 3, "title": "Newest", "release_date": "2024-03-01", "length": 10},
                {"id": 2, "title": "Middle", "created_at": 1706745600, "length": 10},
                {"id": 1, "title": "Oldest", "release_date": "2024-01-01", "length": 10},
            ],
            **LAST_PAGE_META,
        }

    _api_get(provider).side_effect = api_get
    episodes = [episode async for episode in provider.get_podcast_episodes("55")]
    assert [(episode.item_id, episode.position) for episode in episodes] == [
        ("3", 3),
        ("2", 2),
        ("1", 1),
    ]
    assert all(isinstance(episode.podcast, Podcast) for episode in episodes)


async def test_resume_position_and_play_report(provider: TwentyFourSixProvider) -> None:
    """A resumed episode reports only the seconds listened since its resume point."""
    _api_post(provider).return_value = {"id": 66, "length": 1800, "history": {"current": 600}}
    assert await provider.get_resume_position("66", MediaType.PODCAST_EPISODE) == (
        False,
        600_000,
        None,
    )
    _api_post(provider).assert_awaited_once_with("podcast/content/66")
    assert await provider.get_resume_position("33", MediaType.TRACK) == (False, 0, None)

    log_playback = cast("AsyncMock", provider.api.log_playback)
    episode = cast("Any", provider)  # the media item is not used by the provider
    await provider.on_played(MediaType.PODCAST_EPISODE, "66", False, 900, episode, is_playing=False)
    log_playback.assert_awaited_once_with(item_id="66", seconds=300, current=900)
    # the resume point is consumed: a later play of the same episode starts from scratch
    await provider.on_played(MediaType.PODCAST_EPISODE, "66", False, 100, episode, is_playing=False)
    log_playback.assert_awaited_with(item_id="66", seconds=100, current=100)


async def test_on_played_reports_tracks_and_episodes_only(
    provider: TwentyFourSixProvider,
) -> None:
    """A play is logged once when it ends, like the app does, never for radio or ticks."""
    log_playback = cast("AsyncMock", provider.api.log_playback)
    track = Track(
        item_id="33",
        provider=provider.instance_id,
        name="T",
        provider_mappings={_mapping(provider, "33")},
    )
    # periodic progress ticks while playing are not plays
    await provider.on_played(MediaType.TRACK, "33", False, 42, track, is_playing=True)
    log_playback.assert_not_awaited()
    # the play ended (stopped, skipped or finished): report the seconds listened
    await provider.on_played(MediaType.TRACK, "33", False, 42, track, is_playing=False)
    log_playback.assert_awaited_once_with(item_id="33", seconds=42, current=42)
    await provider.on_played(MediaType.TRACK, "33", True, 180, track, is_playing=False)
    log_playback.assert_awaited_with(item_id="33", seconds=180, current=180)
    # marked as unplayed in the UI, or radio: nothing to report
    await provider.on_played(MediaType.TRACK, "33", False, 0, track, is_playing=False)
    await provider.on_played(MediaType.RADIO, "77", False, 42, _radio(provider))
    assert log_playback.await_count == 2


async def test_library_podcasts_respect_profile(provider: TwentyFourSixProvider) -> None:
    """A profile without podcast access yields no library podcasts."""
    provider.api.profile = {"allowed": {"podcast": False, "radio": True}}
    assert [item async for item in provider.get_library_podcasts()] == []
    _api_get(provider).assert_not_awaited()

    provider.api.profile = {}
    _api_get(provider).return_value = {"data": [{"id": 55, "title": "Show"}], **LAST_PAGE_META}
    podcasts = [item async for item in provider.get_library_podcasts()]
    assert [podcast.item_id for podcast in podcasts] == ["55"]


async def test_paginate_caps_and_warns(
    provider: TwentyFourSixProvider, caplog: pytest.LogCaptureFixture
) -> None:
    """A capped listing stops early; hitting the page guard is reported, not silent."""
    _api_get(provider).return_value = {
        "data": [{"id": i + 1} for i in range(3)],
        "meta": {"pagination": {"next_page": 2}},
    }
    items = [item async for item in provider._paginate("music/collection", {}, max_items=5)]
    assert len(items) == 6
    assert _api_get(provider).await_count == 2

    _api_get(provider).reset_mock()
    with caplog.at_level(logging.WARNING):
        items = [item async for item in provider._paginate("music/collection", {})]
    assert len(items) == 3 * 500
    assert "Stopped listing music/collection after 500 pages" in caplog.text


def test_pagination_helpers() -> None:
    """Page counts derive from the reported totals; next pages from any of the known hints."""
    assert total_pages({"total": 73, "per_page": 200, "next_page": None}) == 1
    assert total_pages({"total": 401, "per_page": 200}) == 3
    assert total_pages({"total": 0, "per_page": 200}) == 0
    assert total_pages({"total_pages": 4, "total": 1, "per_page": 1}) == 4
    assert total_pages({"total": "x", "per_page": 200}) is None
    assert total_pages({}) is None
    assert has_next_page({"next_page": 2}, 1, 200) is True
    assert has_next_page({"next_page": None, "total_pages": 5}, 1, 200) is False
    assert has_next_page({"total_pages": 3, "current_page": 1}, 1, 200) is True
    assert has_next_page({"total_pages": 3}, 3, 200) is False
    assert has_next_page({"per_page": 200}, 1, 200) is True
    assert has_next_page({"per_page": 200}, 1, 199) is False
    assert has_next_page({}, 1, 200) is False
