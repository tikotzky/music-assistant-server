"""Tests for the 24six provider implementation."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from music_assistant_models.enums import MediaType, StreamType
from music_assistant_models.errors import UnsupportedFeaturedException
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

from music_assistant.providers.twentyfour_six.provider import (
    TwentyFourSixProvider,
    _has_next_page,
    _total_pages,
)

PLAYLIST_PAGE_1: dict[str, Any] = {
    "playlist": {
        "id": 44,
        "title": "Big Playlist",
        "mine": True,
        "contents": [{"id": 1, "title": "One"}, {"id": 2, "title": "Two"}],
        "pagination": {"total": 3, "per_page": 2, "current_page": 1, "total_pages": 2},
    }
}
PLAYLIST_PAGE_2: dict[str, Any] = {
    "playlist": {
        "id": 44,
        "title": "Big Playlist",
        "mine": True,
        "contents": [{"id": 3, "title": "Three"}],
        "pagination": {"total": 3, "per_page": 2, "current_page": 2, "total_pages": 2},
    }
}


def _api_get(provider: TwentyFourSixProvider) -> AsyncMock:
    return cast("AsyncMock", provider.api.api_get)


def _api_post(provider: TwentyFourSixProvider) -> AsyncMock:
    return cast("AsyncMock", provider.api.api_post)


async def test_search_maps_result_keys(provider: TwentyFourSixProvider) -> None:
    """Search reads every result list, including the renamed content/songs key."""
    _api_post(provider).return_value = {
        "artists": [{"id": 1, "name": "A"}],
        "collections": [{"id": 2, "title": "B"}],
        "songs": [{"id": 3, "title": "C"}, None],
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

    _api_post(provider).return_value = {"content": [{"id": 5, "title": "E"}]}
    results = await provider.search("query", [MediaType.TRACK], 5)
    assert [item.item_id for item in results.tracks] == ["5"]


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

    async def api_get(endpoint: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        assert endpoint == "music/playlist/44"
        return PLAYLIST_PAGE_2 if (params or {}).get("page") == "2" else PLAYLIST_PAGE_1

    _api_get(provider).side_effect = api_get
    first = await provider.get_playlist_tracks("44", page=0)
    assert [(track.item_id, track.position) for track in first] == [("1", 1), ("2", 2)]
    second = await provider.get_playlist_tracks("44", page=1)
    assert [(track.item_id, track.position) for track in second] == [("3", 3)]

    _api_get(provider).reset_mock()
    assert await provider.get_playlist_tracks("44", page=2) == []
    # only the first page is consulted to learn the page count, page 3 is never requested
    assert [call.kwargs["params"]["page"] for call in _api_get(provider).await_args_list] == ["1"]


async def test_remove_playlist_tracks_replaces_remaining_tracks(
    provider: TwentyFourSixProvider,
) -> None:
    """Removing tracks rewrites the playlist with the tracks that remain, across pages."""

    async def api_get(_endpoint: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return PLAYLIST_PAGE_2 if (params or {}).get("page") == "2" else PLAYLIST_PAGE_1

    _api_get(provider).side_effect = api_get
    await provider.remove_playlist_tracks("44", (2,))
    api_patch = cast("AsyncMock", provider.api.api_patch)
    api_patch.assert_awaited_once_with(
        "music/playlist/44",
        params=[("content[]", "1"), ("content[]", "3"), ("force", "0"), ("name", "Big Playlist")],
    )


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

    _api_post(provider).return_value = {"id": 34, "title": "T"}
    stream_url.return_value = "https://stream.mux.com/abc.m3u8?token=1"
    details = await provider.get_stream_details("34", MediaType.PODCAST_EPISODE)
    stream_url.assert_awaited_with("content/34/play", {"format": "m4a"})
    assert details.stream_type == StreamType.HLS
    assert _api_post(provider).await_args_list[-1].args[0] == "podcast/content/34"


async def test_stream_details_for_radio(provider: TwentyFourSixProvider) -> None:
    """A radio station streams its live HLS feed and cannot seek."""
    stream_url = cast("AsyncMock", provider.api.api_get_stream_url)
    stream_url.return_value = "https://live.example.com/radio/index.m3u8"
    details = await provider.get_stream_details("77", MediaType.RADIO)
    stream_url.assert_awaited_once_with("radio/77/play", {"livestream": "1", "format": "m3u8"})
    assert details.stream_type == StreamType.HLS
    assert details.can_seek is False
    _api_post(provider).assert_not_awaited()


async def test_similar_tracks_and_artists(provider: TwentyFourSixProvider) -> None:
    """Similar tracks use the app's autoplay endpoint, similar artists the artist filter."""
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


async def test_artist_toptracks_single_page(provider: TwentyFourSixProvider) -> None:
    """Top tracks are one page of the artist's most popular tracks, not the whole catalog."""
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


async def test_create_playlist_is_editable(provider: TwentyFourSixProvider) -> None:
    """A playlist we created is editable even though the create response omits ownership."""
    _api_post(provider).return_value = {"playlist": {"id": 77, "title": "Mine"}}
    playlist = await provider.create_playlist("Mine", {MediaType.TRACK})
    _api_post(provider).assert_awaited_once_with("music/playlist", params={"name": "Mine"})
    assert playlist.is_editable is True
    assert next(iter(playlist.provider_mappings)).is_unique is True


async def test_recommendation_rows_and_items(provider: TwentyFourSixProvider) -> None:
    """Rows have stable ids and their items come from the matching listing endpoint."""
    rows = await provider.get_recommendations()
    row_ids = [row.item_id for row in rows]
    assert row_ids[:2] == ["banners", "by24Six"]
    assert {"newAlbums", "stories", "trending", "recent", "newPodcasts"} <= set(row_ids)
    assert all(row.items == [] for row in rows)
    assert all(row.translation_key for row in rows)

    # rows for content the profile may not access are left out
    provider.api.profile = {"allowed": {"stories": False, "podcast": False, "music": True}}
    row_ids = [row.item_id for row in await provider.get_recommendations()]
    assert "stories" not in row_ids
    assert "newPodcasts" not in row_ids
    assert "newAlbums" in row_ids
    provider.api.profile = {}

    _api_get(provider).return_value = {
        "data": [
            {"id": 1, "type": "collection", "title": "Album"},
            {"id": 2, "type": "artist", "name": "Artist"},
            {"id": 3, "type": "playlist", "title": "List"},
            {"id": 4, "type": "content", "title": "Song", "length": 100},
            {"id": 5, "type": "unknown"},
        ]
    }
    items = await provider.get_recommendation_items("newAlbums")
    _api_get(provider).assert_awaited_once_with(
        "music/collection",
        params={"sort": "newAlbums", "with_contents": "0", "page": "1", "per_page": "50"},
    )
    assert [type(item) for item in items] == [Album, Artist, Playlist, Track]
    assert await provider.get_recommendation_items("nope") == []


async def test_recommendation_banners_resolve_entities(provider: TwentyFourSixProvider) -> None:
    """Featured banners resolve to the full playlist/album they point at."""

    async def api_get(endpoint: str, **_kwargs: Any) -> dict[str, Any]:
        if endpoint == "music":
            return {
                "banners": [
                    {"entity_id": 44, "entity_type": "playlist"},
                    {"entity_id": 22, "entity_type": "collection"},
                    {"entity_id": None, "entity_type": "collection"},
                ]
            }
        if endpoint == "music/playlist/44":
            return {"playlist": {"id": 44, "title": "Featured list"}}
        if endpoint == "music/collection/22":
            return {"collection": {"id": 22, "title": "Featured album"}}
        raise AssertionError(f"unexpected endpoint {endpoint}")

    _api_get(provider).side_effect = api_get
    items = await provider.get_recommendation_items("banners")
    assert [(type(item), item.item_id) for item in items] == [(Playlist, "44"), (Album, "22")]


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
    cast("AsyncMock", provider.api.api_delete).assert_awaited_once_with("music/library/content/33")

    await provider.set_favorite("55", MediaType.PODCAST, True)
    assert _api_post(provider).await_args_list[-1].args == ("podcast/collection/55/favorite",)
    await provider.set_favorite("44", MediaType.PLAYLIST, True)
    assert _api_post(provider).await_count == 2

    assert await provider.library_add(_radio(provider)) is False


async def test_browse_categories(provider: TwentyFourSixProvider) -> None:
    """Categories are browsable folders that list the releases of a category."""
    _api_get(provider).return_value = {"data": [{"id": 3, "title": "Wedding"}, {"title": "x"}]}
    folders = cast("list[BrowseFolder]", await provider.browse("twentyfour_six--test://categories"))
    assert [(folder.item_id, folder.name, folder.path) for folder in folders] == [
        ("3", "Wedding", "twentyfour_six--test://category/3")
    ]

    _api_get(provider).return_value = {"releases": [{"id": 22, "title": "Album"}]}
    albums = await provider.browse("twentyfour_six--test://category/3")
    _api_get(provider).assert_awaited_with("music/category/3")
    assert [item.item_id for item in albums] == ["22"]


async def test_browse_stories(provider: TwentyFourSixProvider) -> None:
    """Stories are a root folder listing the story albums, hidden without access."""
    _api_get(provider).return_value = {
        "data": [
            {"id": 5, "type": "collection", "title": "Bedtime Tales", "contents": [{"id": 1}]}
        ],
        "meta": {"pagination": {"next_page": None}},
    }
    stories = await provider.browse("twentyfour_six--test://stories")
    _api_get(provider).assert_awaited_once_with(
        "music/collection",
        params={"per_page": "200", "sort": "newStories", "with_contents": "0", "page": "1"},
    )
    assert [(type(item), item.item_id, item.name) for item in stories] == [
        (Album, "5", "Bedtime Tales")
    ]

    music = cast("Any", provider.mass).music
    for controller in ("artists", "albums", "tracks", "playlists", "podcasts", "radio"):
        getattr(music, controller).library_items = AsyncMock(return_value=[])
    root = cast("list[BrowseFolder]", await provider.browse("twentyfour_six--test://"))
    assert [folder.item_id for folder in root][-2:] == ["categories", "stories"]
    provider.api.profile = {"allowed": {"stories": False}}
    root = cast("list[BrowseFolder]", await provider.browse("twentyfour_six--test://"))
    assert "stories" not in [folder.item_id for folder in root]


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
                {"id": 2, "title": "Middle", "release_date": "2024-02-01", "length": 10},
                {"id": 1, "title": "Oldest", "release_date": "2024-01-01", "length": 10},
            ],
            "meta": {"pagination": {"next_page": None}},
        }

    _api_get(provider).side_effect = api_get
    episodes = [episode async for episode in provider.get_podcast_episodes("55")]
    assert [(episode.item_id, episode.position) for episode in episodes] == [
        ("3", 3),
        ("2", 2),
        ("1", 1),
    ]
    assert all(isinstance(episode.podcast, Podcast) for episode in episodes)


async def test_resume_position(provider: TwentyFourSixProvider) -> None:
    """The resume position of an episode comes from its listening history."""
    _api_post(provider).return_value = {"id": 66, "length": 1800, "history": {"current": 600}}
    assert await provider.get_resume_position("66", MediaType.PODCAST_EPISODE) == (
        False,
        600_000,
        None,
    )
    _api_post(provider).assert_awaited_once_with("podcast/content/66")
    assert await provider.get_resume_position("33", MediaType.TRACK) == (False, 0, None)


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
    _api_get(provider).return_value = {"data": [{"id": 55, "title": "Show"}]}
    podcasts = [item async for item in provider.get_library_podcasts()]
    assert [podcast.item_id for podcast in podcasts] == ["55"]


def test_total_pages_derived_from_totals() -> None:
    """The API reports totals and a page size; the page count is derived from them."""
    assert _total_pages({"total": 73, "per_page": 200, "next_page": None}) == 1
    assert _total_pages({"total": 401, "per_page": 200}) == 3
    assert _total_pages({"total": 0, "per_page": 200}) == 0
    assert _total_pages({"total_pages": 4, "total": 1, "per_page": 1}) == 4
    assert _total_pages({}) is None


def test_has_next_page() -> None:
    """Pagination is read from next_page, total_pages or the page size, in that order."""
    assert _has_next_page({"next_page": 2}, 1, 200) is True
    assert _has_next_page({"next_page": None, "total_pages": 5}, 1, 200) is False
    assert _has_next_page({"total_pages": 3, "current_page": 1}, 1, 200) is True
    assert _has_next_page({"total_pages": 3}, 3, 200) is False
    assert _has_next_page({"per_page": 200}, 1, 200) is True
    assert _has_next_page({"per_page": 200}, 1, 199) is False
    assert _has_next_page({}, 1, 200) is False


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
