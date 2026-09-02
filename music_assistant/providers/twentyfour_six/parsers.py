"""Parsers for 24six API responses to Music Assistant models."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from music_assistant_models.enums import AlbumType, ContentType, ImageType, MediaType
from music_assistant_models.media_items import (
    Album,
    Artist,
    AudioFormat,
    ItemMapping,
    MediaItemImage,
    Playlist,
    Podcast,
    PodcastEpisode,
    ProviderMapping,
    Radio,
    Track,
    UniqueList,
)

from music_assistant.helpers.util import infer_album_type, parse_title_and_version

from .constants import FULLY_PLAYED_THRESHOLD

if TYPE_CHECKING:
    from .provider import TwentyFourSixProvider


def parse_artist(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Artist:
    """
    Parse a 24six artist object to a Music Assistant Artist.

    :param provider: The provider instance.
    :param data: Raw API data for the artist.
    """
    artist_id = str(data["id"])
    artist = Artist(
        item_id=artist_id,
        provider=provider.instance_id,
        name=data.get("name") or "",
        provider_mappings={
            ProviderMapping(
                item_id=artist_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url") or None,
            )
        },
    )
    if img := data.get("img"):
        artist.metadata.images = UniqueList([_image(provider, img)])
    if bio := data.get("bio"):
        artist.metadata.description = str(bio)
    artist.favorite = bool(data.get("is_favorite"))
    return artist


def parse_album(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Album:
    """
    Parse a 24six collection object to a Music Assistant Album.

    :param provider: The provider instance.
    :param data: Raw API data for the collection.
    """
    album_id = str(data["id"])
    name, version = parse_title_and_version(data.get("title") or "")
    album = Album(
        item_id=album_id,
        provider=provider.instance_id,
        name=name,
        version=version,
        provider_mappings={
            ProviderMapping(
                item_id=album_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url") or None,
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
    )
    release_date = parse_release_date(data)
    if release_date:
        album.year = release_date.year
        album.metadata.release_date = release_date
    elif year_val := data.get("year"):
        with suppress(ValueError, TypeError):
            album.year = int(year_val)

    for artist_data in data.get("artists") or []:
        if artist_data and artist_data.get("id"):
            album.artists.append(parse_artist(provider, artist_data))

    if img_url := _get_best_image(data):
        album.metadata.images = UniqueList([_image(provider, img_url)])
    if description := data.get("description"):
        album.metadata.description = str(description)
    if genres := _category_names(data):
        album.metadata.genres = genres

    album.album_type = infer_album_type(album.name, album.version)
    contents = data.get("contents")
    if album.album_type == AlbumType.UNKNOWN and isinstance(contents, list) and len(contents) == 1:
        album.album_type = AlbumType.SINGLE
    album.favorite = bool(data.get("is_favorite"))
    return album


def parse_track(
    provider: TwentyFourSixProvider,
    data: dict[str, Any],
    fallback_artists: list[Artist] | None = None,
) -> Track:
    """
    Parse a 24six content object to a Music Assistant Track.

    :param provider: The provider instance.
    :param data: Raw API data for the track.
    :param fallback_artists: Artists to use when the track data has none (e.g. album artists).
    """
    track_id = str(data["id"])
    name, version = parse_title_and_version(data.get("title") or "")
    track = Track(
        item_id=track_id,
        provider=provider.instance_id,
        name=name,
        version=version,
        duration=data.get("length") or data.get("duration") or 0,
        track_number=data.get("track_num") or 0,
        disc_number=data.get("disc_num") or 0,
        provider_mappings={
            ProviderMapping(
                item_id=track_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url") or None,
                available=not data.get("unplayable", False),
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
    )
    track.artists = UniqueList()
    for artist_data in data.get("artists") or []:
        if artist_data and artist_data.get("id"):
            track.artists.append(parse_artist(provider, artist_data))
    if not track.artists and fallback_artists:
        track.artists = UniqueList(fallback_artists)

    if collection_id := data.get("collection_id"):
        track.album = _album_mapping(provider, str(collection_id), data.get("collection"))

    if img_url := _get_best_image(data):
        track.metadata.images = UniqueList([_image(provider, img_url)])
    if release_date := parse_release_date(data):
        track.metadata.release_date = release_date
    if lyrics := data.get("lyrics"):
        track.metadata.lyrics = str(lyrics)
    if lrc_lyrics := _lrc_lyrics(data.get("lyrics_sync")):
        track.metadata.lrc_lyrics = lrc_lyrics

    track.favorite = bool(data.get("is_favorite"))
    return track


def parse_playlist(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Playlist:
    """
    Parse a 24six playlist object to a Music Assistant Playlist.

    :param provider: The provider instance.
    :param data: Raw API data for the playlist.
    """
    playlist_id = str(data["id"])
    is_mine = bool(data.get("mine", False))
    playlist = Playlist(
        item_id=playlist_id,
        provider=provider.instance_id,
        name=data.get("title") or "",
        is_editable=is_mine,
        provider_mappings={
            ProviderMapping(
                item_id=playlist_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url") or None,
                is_unique=is_mine,
            )
        },
    )
    if owner_profile := data.get("profile"):
        playlist.owner = owner_profile.get("name") or "24six"
    else:
        playlist.owner = "24six"

    if img_url := _get_best_image(data):
        playlist.metadata.images = UniqueList([_image(provider, img_url)])
    if description := data.get("description"):
        playlist.metadata.description = str(description)

    playlist.favorite = bool(data.get("is_favorite"))
    return playlist


def parse_podcast(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Podcast:
    """
    Parse a 24six podcast collection object to a Music Assistant Podcast.

    :param provider: The provider instance.
    :param data: Raw API data for the podcast collection.
    """
    podcast_id = str(data["id"])
    podcast = Podcast(
        item_id=podcast_id,
        provider=provider.instance_id,
        name=data.get("title") or "",
        provider_mappings={
            ProviderMapping(
                item_id=podcast_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url") or None,
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
    )
    publishers = [
        artist_data.get("name")
        for artist_data in data.get("artists") or []
        if artist_data and artist_data.get("name")
    ]
    if publishers:
        podcast.publisher = ", ".join(publishers)
    if contents := data.get("contents"):
        podcast.total_episodes = len(contents)
    if img_url := _get_best_image(data):
        podcast.metadata.images = UniqueList([_image(provider, img_url)])
    if description := data.get("description"):
        podcast.metadata.description = str(description)
    if genres := _category_names(data):
        podcast.metadata.genres = genres
    podcast.favorite = bool(data.get("is_favorite"))
    return podcast


def parse_podcast_episode(
    provider: TwentyFourSixProvider,
    data: dict[str, Any],
    position: int = 0,
    podcast: Podcast | ItemMapping | None = None,
) -> PodcastEpisode:
    """
    Parse a 24six podcast content object to a Music Assistant PodcastEpisode.

    :param provider: The provider instance.
    :param data: Raw API data for the episode.
    :param position: Sort position of the episode (0 when unknown).
    :param podcast: The parent podcast, when the episode data does not carry it.
    """
    episode_id = str(data["id"])
    collection_id = data.get("collection_id")
    if podcast is None:
        if not collection_id:
            msg = f"Episode {episode_id} has no podcast reference"
            raise ValueError(msg)
        podcast = _podcast_mapping(provider, str(collection_id), data.get("collection"))
    duration = int(data.get("length") or data.get("duration") or 0)
    episode = PodcastEpisode(
        item_id=episode_id,
        provider=provider.instance_id,
        name=data.get("title") or "",
        position=position,
        podcast=podcast,
        duration=duration,
        provider_mappings={
            ProviderMapping(
                item_id=episode_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url") or None,
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
    )
    resume_seconds = parse_resume_position(data)
    if resume_seconds is not None:
        episode.resume_position_ms = resume_seconds * 1000
        episode.fully_played = is_fully_played(resume_seconds, duration)
    if img_url := _get_best_image(data):
        episode.metadata.images = UniqueList([_image(provider, img_url)])
    if description := data.get("description"):
        episode.metadata.description = str(description)
    if release_date := parse_release_date(data, created_fallback=True):
        episode.metadata.release_date = release_date
    episode.favorite = bool(data.get("is_favorite"))
    return episode


def parse_radio(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Radio:
    """
    Parse a 24six radio station object to a Music Assistant Radio.

    :param provider: The provider instance.
    :param data: Raw API data for the radio station.
    """
    radio_id = str(data["id"])
    radio = Radio(
        item_id=radio_id,
        provider=provider.instance_id,
        name=data.get("title") or data.get("name") or "",
        provider_mappings={
            ProviderMapping(
                item_id=radio_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url") or None,
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
    )
    if img_url := _get_best_image(data):
        radio.metadata.images = UniqueList([_image(provider, img_url)])
    if description := data.get("description") or data.get("subtitle"):
        radio.metadata.description = str(description)
    return radio


def parse_release_date(data: dict[str, Any], created_fallback: bool = False) -> datetime | None:
    """
    Parse the release date of a 24six object, if any.

    :param data: Raw API data carrying an optional ``release_date`` field.
    :param created_fallback: Use the ``created_at`` timestamp when there is no release date
        (podcast episodes only carry the former).
    """
    release_date = data.get("release_date")
    if not release_date:
        if created_fallback and data.get("created_at"):
            with suppress(ValueError, TypeError, OverflowError):
                return datetime.fromtimestamp(float(data["created_at"]), tz=UTC)
        return None
    parsed: datetime | None = None
    with suppress(ValueError, TypeError):
        parsed = datetime.fromisoformat(str(release_date))
    if parsed is None:
        with suppress(ValueError, TypeError):
            parsed = datetime.strptime(str(release_date)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    return _as_utc(parsed)


def parse_resume_position(data: dict[str, Any]) -> int | None:
    """
    Return the last known playback position (in seconds) of a content object.

    :param data: Raw API data carrying the ``history`` / ``current`` progress fields.
    """
    history = data.get("history")
    candidates = [
        history.get("current") if isinstance(history, dict) else None,
        data.get("current"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        with suppress(ValueError, TypeError):
            return max(int(float(candidate)), 0)
    return None


def parse_resume_timestamp(data: dict[str, Any]) -> datetime | None:
    """
    Return when the playback position of a content object was last updated, if known.

    :param data: Raw API data carrying the ``history`` progress object.
    """
    history = data.get("history")
    if not isinstance(history, dict):
        return None
    timestamp = history.get("timestamp") or data.get("current_ts")
    if not timestamp:
        return None
    with suppress(ValueError, TypeError, OverflowError):
        return datetime.fromtimestamp(float(timestamp), tz=UTC)
    with suppress(ValueError, TypeError):
        return _as_utc(datetime.fromisoformat(str(timestamp)))
    return None


def is_fully_played(position: int, duration: int) -> bool:
    """
    Return whether a playback position counts as having fully played the item.

    :param position: Playback position in seconds.
    :param duration: Duration of the item in seconds.
    """
    return duration > 0 and position >= duration * FULLY_PLAYED_THRESHOLD


def get_audio_format(data: dict[str, Any]) -> str | None:
    """
    Return the stream format declared by a content object, if any.

    :param data: Raw API data for the content.
    """
    audio_format = data.get("audio_format")
    return str(audio_format) if audio_format else None


def _as_utc(value: datetime | None) -> datetime | None:
    """Return the datetime as timezone-aware, assuming UTC when it has no timezone."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _album_mapping(
    provider: TwentyFourSixProvider, collection_id: str, collection_data: dict[str, Any] | None
) -> ItemMapping:
    """Build the album ItemMapping for a track from its (optional) embedded collection."""
    album_name = ""
    album_image: MediaItemImage | None = None
    if collection_data:
        album_name, _ = parse_title_and_version(collection_data.get("title") or "")
        if img_path := _get_best_image(collection_data):
            album_image = _image(provider, img_path)
    return ItemMapping(
        media_type=MediaType.ALBUM,
        item_id=collection_id,
        provider=provider.instance_id,
        name=album_name,
        image=album_image,
    )


def _podcast_mapping(
    provider: TwentyFourSixProvider, collection_id: str, collection_data: dict[str, Any] | None
) -> ItemMapping:
    """Build the podcast ItemMapping for an episode from its (optional) embedded collection."""
    podcast_name = ""
    podcast_image: MediaItemImage | None = None
    if collection_data:
        podcast_name = collection_data.get("title") or ""
        if img_path := _get_best_image(collection_data):
            podcast_image = _image(provider, img_path)
    return ItemMapping(
        media_type=MediaType.PODCAST,
        item_id=collection_id,
        provider=provider.instance_id,
        name=podcast_name,
        image=podcast_image,
    )


def _image(provider: TwentyFourSixProvider, path: str) -> MediaItemImage:
    """Build a remotely accessible thumbnail image for the given URL."""
    return MediaItemImage(
        type=ImageType.THUMB,
        path=path,
        provider=provider.instance_id,
        remotely_accessible=True,
    )


def _get_best_image(data: dict[str, Any]) -> str | None:
    """Extract the best image URL from a 24six data object."""
    # collections carry an artwork list with typed images, prefer the cover
    if artwork := data.get("artwork"):
        for art in artwork:
            if art and art.get("type") == "cover":
                url: str | None = art.get("large") or art.get("img")
                if url:
                    return url
    result: str | None = data.get("img") or None
    return result


def _category_names(data: dict[str, Any]) -> set[str]:
    """Return the category titles of a 24six object as a set of genre names."""
    return {
        str(category.get("title"))
        for category in data.get("categories") or []
        if category and category.get("title")
    }


def _lrc_lyrics(lyrics_sync: Any) -> str | None:
    """
    Convert the synced lyrics of a track to LRC format.

    The API either delivers LRC text directly or a list of timed lines.

    :param lyrics_sync: The raw ``lyrics_sync`` value.
    """
    if not lyrics_sync:
        return None
    if isinstance(lyrics_sync, str):
        return lyrics_sync if lyrics_sync.lstrip().startswith("[") else None
    if not isinstance(lyrics_sync, list):
        return None
    lines: list[str] = []
    for entry in lyrics_sync:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or entry.get("line") or ""
        timestamp = entry.get("time", entry.get("start", entry.get("ts")))
        if timestamp is None:
            continue
        try:
            seconds = float(timestamp)
        except TypeError, ValueError:
            continue
        minutes, remainder = divmod(seconds, 60)
        lines.append(f"[{int(minutes):02d}:{remainder:05.2f}]{text}")
    return "\n".join(lines) if lines else None
