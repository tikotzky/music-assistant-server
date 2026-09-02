"""Tests for the 24six response parsers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from music_assistant_models.enums import AlbumType, ImageType, MediaType
from music_assistant_models.media_items import ItemMapping

from music_assistant.providers.twentyfour_six.parsers import (
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
from music_assistant.providers.twentyfour_six.provider import TwentyFourSixProvider

ARTIST_OBJ: dict[str, Any] = {
    "id": 11,
    "type": "artist",
    "name": "Test Artist",
    "img": "https://img.example.com/artist.jpg",
    "bio": "An artist biography",
    "preview_url": "https://24six.app/artist/11",
    "is_favorite": True,
}

ALBUM_OBJ: dict[str, Any] = {
    "id": 22,
    "type": "collection",
    "title": "Test Album (Deluxe Edition)",
    "release_date": "2024-03-05",
    "artists": [ARTIST_OBJ],
    "artwork": [
        {"type": "jacket", "large": "https://img.example.com/jacket.jpg"},
        {"type": "cover", "large": "https://img.example.com/cover.jpg", "img": "small.jpg"},
    ],
    "img": "https://img.example.com/fallback.jpg",
    "description": "Album notes",
    "categories": [{"id": 1, "title": "Chassidic"}, {"id": 2, "title": "Wedding"}],
}

TRACK_OBJ: dict[str, Any] = {
    "id": 33,
    "type": "content",
    "title": "Test Track",
    "length": 245,
    "track_num": 3,
    "collection_id": 22,
    "collection": {"id": 22, "title": "Test Album", "img": "https://img.example.com/album.jpg"},
    "artists": [ARTIST_OBJ],
    "img": "https://img.example.com/track.jpg",
    "lyrics": "Plain lyrics",
    "lyrics_sync": [
        {"text": "First line", "time": 1.5},
        {"text": "Second line", "time": 65.25},
        {"text": "No time"},
    ],
    "audio_format": "mp3",
}

PLAYLIST_OBJ: dict[str, Any] = {
    "id": 44,
    "type": "playlist",
    "title": "My Playlist",
    "mine": True,
    "profile": {"id": 5, "name": "Mordy"},
    "img": "https://img.example.com/playlist.jpg",
    "description": "Playlist notes",
}

PODCAST_OBJ: dict[str, Any] = {
    "id": 55,
    "type": "collection",
    "content_type": "podcast",
    "title": "Test Podcast",
    "artists": [{"id": 12, "name": "Host One"}, {"id": 13, "name": "Host Two"}],
    "contents": [{"id": 1}, {"id": 2}],
    "img": "https://img.example.com/podcast.jpg",
    "description": "Podcast notes",
}

EPISODE_OBJ: dict[str, Any] = {
    "id": 66,
    "type": "content",
    "content_type": "podcast",
    "title": "Episode One",
    "length": 1800,
    "collection_id": 55,
    "collection": {"id": 55, "title": "Test Podcast", "img": "https://img.example.com/p.jpg"},
    "release_date": "2024-01-02T03:04:05Z",
    "history": {"current": 1750, "timestamp": 1704164645},
    "description": "Episode notes",
}

RADIO_OBJ: dict[str, Any] = {
    "id": 77,
    "type": "radio",
    "title": "24six Radio",
    "img": "https://img.example.com/radio.jpg",
    "subtitle": "Always on",
}


def test_parse_artist(provider: TwentyFourSixProvider) -> None:
    """An artist gets its image, biography, favorite flag and provider mapping."""
    artist = parse_artist(provider, ARTIST_OBJ)
    assert artist.item_id == "11"
    assert artist.name == "Test Artist"
    assert artist.favorite is True
    assert artist.metadata.description == "An artist biography"
    assert artist.metadata.images is not None
    assert artist.metadata.images[0].path == "https://img.example.com/artist.jpg"
    assert artist.metadata.images[0].type == ImageType.THUMB
    mapping = next(iter(artist.provider_mappings))
    assert mapping.provider_instance == provider.instance_id
    assert mapping.url == "https://24six.app/artist/11"


def test_parse_album(provider: TwentyFourSixProvider) -> None:
    """An album splits the version off its title and prefers the cover artwork."""
    album = parse_album(provider, ALBUM_OBJ)
    assert album.item_id == "22"
    assert album.name == "Test Album"
    assert album.version == "Deluxe Edition"
    assert album.year == 2024
    assert album.metadata.release_date == datetime(2024, 3, 5, tzinfo=UTC)
    assert album.album_type == AlbumType.UNKNOWN
    assert [artist.name for artist in album.artists] == ["Test Artist"]
    assert album.metadata.images is not None
    assert album.metadata.images[0].path == "https://img.example.com/cover.jpg"
    assert album.metadata.description == "Album notes"
    assert album.metadata.genres == {"Chassidic", "Wedding"}


def test_parse_album_type_hints(provider: TwentyFourSixProvider) -> None:
    """A one-track collection is a single, a live indicator in the title wins."""
    single = parse_album(provider, {"id": 1, "title": "Song", "contents": [{"id": 9}]})
    assert single.album_type == AlbumType.SINGLE
    live = parse_album(provider, {"id": 2, "title": "Concert (Live)", "contents": [{"id": 9}]})
    assert live.album_type == AlbumType.LIVE


def test_parse_track(provider: TwentyFourSixProvider) -> None:
    """A track carries its album mapping, lyrics and synced lyrics in LRC format."""
    track = parse_track(provider, TRACK_OBJ)
    assert track.item_id == "33"
    assert track.duration == 245
    assert track.track_number == 3
    assert isinstance(track.album, ItemMapping)
    assert track.album.item_id == "22"
    assert track.album.media_type == MediaType.ALBUM
    assert track.album.name == "Test Album"
    assert track.album.image is not None
    assert track.album.image.path == "https://img.example.com/album.jpg"
    assert [artist.name for artist in track.artists] == ["Test Artist"]
    assert track.metadata.lyrics == "Plain lyrics"
    assert track.metadata.lrc_lyrics == "[00:01.50]First line\n[01:05.25]Second line"
    assert get_audio_format(TRACK_OBJ) == "mp3"


def test_parse_track_falls_back_to_album_artists(provider: TwentyFourSixProvider) -> None:
    """A track without artists takes the artists of the album it came from."""
    album_artist = parse_artist(provider, ARTIST_OBJ)
    track = parse_track(
        provider, {"id": 34, "title": "Song", "length": 10}, fallback_artists=[album_artist]
    )
    assert [artist.item_id for artist in track.artists] == ["11"]
    assert track.album is None
    assert track.metadata.lrc_lyrics is None


def test_parse_track_lrc_lyrics_passthrough(provider: TwentyFourSixProvider) -> None:
    """Synced lyrics that already are LRC text are kept as they are."""
    track = parse_track(
        provider, {"id": 35, "title": "Song", "lyrics_sync": "[00:01.00]Already LRC"}
    )
    assert track.metadata.lrc_lyrics == "[00:01.00]Already LRC"
    track = parse_track(provider, {"id": 36, "title": "Song", "lyrics_sync": "not lrc"})
    assert track.metadata.lrc_lyrics is None


def test_parse_playlist(provider: TwentyFourSixProvider) -> None:
    """An owned playlist is editable and unique to this account."""
    playlist = parse_playlist(provider, PLAYLIST_OBJ)
    assert playlist.item_id == "44"
    assert playlist.is_editable is True
    assert playlist.owner == "Mordy"
    assert playlist.metadata.description == "Playlist notes"
    mapping = next(iter(playlist.provider_mappings))
    assert mapping.is_unique is True

    public = parse_playlist(provider, {**PLAYLIST_OBJ, "mine": False, "profile": None})
    assert public.is_editable is False
    assert public.owner == "24six"
    assert next(iter(public.provider_mappings)).is_unique is False


def test_parse_podcast(provider: TwentyFourSixProvider) -> None:
    """A podcast collection lists its hosts as publisher and counts its episodes."""
    podcast = parse_podcast(provider, PODCAST_OBJ)
    assert podcast.item_id == "55"
    assert podcast.name == "Test Podcast"
    assert podcast.publisher == "Host One, Host Two"
    assert podcast.total_episodes == 2
    assert podcast.metadata.description == "Podcast notes"
    assert podcast.metadata.images is not None
    assert podcast.metadata.images[0].path == "https://img.example.com/podcast.jpg"


def test_parse_podcast_episode(provider: TwentyFourSixProvider) -> None:
    """An episode resolves its podcast, resume position and fully-played state."""
    episode = parse_podcast_episode(provider, EPISODE_OBJ, position=4)
    assert episode.item_id == "66"
    assert episode.position == 4
    assert episode.duration == 1800
    assert isinstance(episode.podcast, ItemMapping)
    assert episode.podcast.item_id == "55"
    assert episode.podcast.media_type == MediaType.PODCAST
    assert episode.resume_position_ms == 1750 * 1000
    assert episode.fully_played is True
    assert episode.metadata.release_date == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert episode.metadata.description == "Episode notes"

    parent = parse_podcast(provider, PODCAST_OBJ)
    in_progress = parse_podcast_episode(
        provider, {**EPISODE_OBJ, "history": {"current": 60}}, podcast=parent
    )
    assert in_progress.podcast is parent
    assert in_progress.resume_position_ms == 60_000
    assert in_progress.fully_played is False


def test_parse_radio(provider: TwentyFourSixProvider) -> None:
    """A radio station maps to a Radio item with image and description."""
    radio = parse_radio(provider, RADIO_OBJ)
    assert radio.item_id == "77"
    assert radio.name == "24six Radio"
    assert radio.metadata.description == "Always on"
    assert radio.metadata.images is not None
    assert radio.metadata.images[0].path == "https://img.example.com/radio.jpg"


def test_parse_release_date_formats() -> None:
    """Release dates are parsed from ISO timestamps and plain dates, never crashing."""
    assert parse_release_date({"release_date": "2023-12-31"}) == datetime(2023, 12, 31, tzinfo=UTC)
    assert parse_release_date({"release_date": "2023-12-31T10:00:00Z"}) == datetime(
        2023, 12, 31, 10, tzinfo=UTC
    )
    assert parse_release_date({"release_date": "garbage"}) is None
    assert parse_release_date({}) is None


def test_resume_helpers() -> None:
    """The resume position and timestamp come from the history, with sane fallbacks."""
    assert parse_resume_position({"history": {"current": "12.7"}}) == 12
    assert parse_resume_position({"current": -3}) == 0
    assert parse_resume_position({}) is None
    assert parse_resume_timestamp({"history": {"timestamp": 1704164645}}) == datetime(
        2024, 1, 2, 3, 4, 5, tzinfo=UTC
    )
    assert parse_resume_timestamp({"history": {"timestamp": "2024-01-02T03:04:05+00:00"}}) == (
        datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    )
    assert parse_resume_timestamp({"history": {}}) is None
    assert is_fully_played(95, 100) is True
    assert is_fully_played(90, 100) is False
    assert is_fully_played(10, 0) is False
