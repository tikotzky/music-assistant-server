"""Parsers for 24six API responses to Music Assistant models."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from music_assistant_models.enums import ContentType, ImageType, MediaType
from music_assistant_models.media_items import (
    Album,
    Artist,
    AudioFormat,
    ItemMapping,
    MediaItemImage,
    Playlist,
    ProviderMapping,
    Track,
    UniqueList,
)

from music_assistant.helpers.util import infer_album_type, parse_title_and_version

if TYPE_CHECKING:
    from .provider import TwentyFourSixProvider


def parse_artist(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Artist:
    """Parse a 24six artist object to a Music Assistant Artist."""
    artist_id = str(data["id"])
    artist = Artist(
        item_id=artist_id,
        provider=provider.instance_id,
        name=data.get("name", ""),
        provider_mappings={
            ProviderMapping(
                item_id=artist_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url", ""),
            )
        },
    )
    if img := data.get("img"):
        artist.metadata.images = UniqueList(
            [
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=img,
                    provider=provider.instance_id,
                    remotely_accessible=True,
                )
            ]
        )
    artist.favorite = bool(data.get("is_favorite"))
    return artist


def parse_album(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Album:
    """Parse a 24six collection object to a Music Assistant Album."""
    album_id = str(data["id"])
    name, version = parse_title_and_version(data.get("title", ""))
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
                url=data.get("preview_url", ""),
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
    )
    # Year from year field or release_date
    if year_val := data.get("year"):
        with suppress(ValueError, TypeError):
            album.year = int(year_val)
    elif release_date := data.get("release_date"):
        with suppress(ValueError, IndexError):
            album.year = int(str(release_date).split("-")[0])

    # Artists
    for artist_data in data.get("artists", []):
        album.artists.append(parse_artist(provider, artist_data))

    # Image - prefer artwork cover, fall back to img
    img_url = _get_best_image(data)
    if img_url:
        album.metadata.images = UniqueList(
            [
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=img_url,
                    provider=provider.instance_id,
                    remotely_accessible=True,
                )
            ]
        )

    album.album_type = infer_album_type(album.name, album.version)
    album.favorite = bool(data.get("is_favorite"))
    return album


def parse_track(
    provider: TwentyFourSixProvider,
    data: dict[str, Any],
    fallback_artists: list[Artist] | None = None,
) -> Track:
    """Parse a 24six content object to a Music Assistant Track.

    :param provider: The provider instance.
    :param data: Raw API data for the track.
    :param fallback_artists: Artists to use when the track data has none (e.g. album artists).
    """
    track_id = str(data["id"])
    name, version = parse_title_and_version(data.get("title", ""))
    track = Track(
        item_id=track_id,
        provider=provider.instance_id,
        name=name,
        version=version,
        duration=data.get("length") or 0,
        track_number=data.get("track_num", 0) or 0,  # or 0: API may return null
        disc_number=data.get("disc_num", 0) or 0,
        provider_mappings={
            ProviderMapping(
                item_id=track_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url", ""),
                available=not data.get("unplayable", False),
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
    )
    # Artists -- fall back to album artists when the track data has none
    track.artists = UniqueList()
    for artist_data in data.get("artists", []):
        track.artists.append(parse_artist(provider, artist_data))
    if not track.artists and fallback_artists:
        track.artists = UniqueList(fallback_artists)

    # Album mapping
    collection_id = data.get("collection_id")
    if collection_id:
        album_name = ""
        album_image: MediaItemImage | None = None
        if collection_data := data.get("collection"):
            album_name, _ = parse_title_and_version(collection_data.get("title", ""))
            if img_path := _get_best_image(collection_data):
                album_image = MediaItemImage(
                    type=ImageType.THUMB,
                    path=img_path,
                    provider=provider.instance_id,
                    remotely_accessible=True,
                )
        track.album = ItemMapping(
            media_type=MediaType.ALBUM,
            item_id=str(collection_id),
            provider=provider.instance_id,
            name=album_name,
            image=album_image,
        )

    # Image
    img_url = _get_best_image(data)
    if img_url:
        track.metadata.images = UniqueList(
            [
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=img_url,
                    provider=provider.instance_id,
                    remotely_accessible=True,
                )
            ]
        )

    track.favorite = bool(data.get("is_favorite"))
    return track


def parse_playlist(provider: TwentyFourSixProvider, data: dict[str, Any]) -> Playlist:
    """Parse a 24six playlist object to a Music Assistant Playlist."""
    playlist_id = str(data["id"])
    playlist = Playlist(
        item_id=playlist_id,
        provider=provider.instance_id,
        name=data.get("title", ""),
        is_editable=bool(data.get("mine", False)),
        provider_mappings={
            ProviderMapping(
                item_id=playlist_id,
                provider_domain=provider.domain,
                provider_instance=provider.instance_id,
                url=data.get("preview_url", ""),
                is_unique=bool(data.get("mine", False)),
            )
        },
    )
    if owner_profile := data.get("profile"):
        playlist.owner = owner_profile.get("name", "24six")
    else:
        playlist.owner = "24six"

    if img := data.get("img"):
        playlist.metadata.images = UniqueList(
            [
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=img,
                    provider=provider.instance_id,
                    remotely_accessible=True,
                )
            ]
        )

    playlist.favorite = bool(data.get("is_favorite"))
    return playlist


def _get_best_image(data: dict[str, Any]) -> str | None:
    """Extract the best image URL from a 24six data object."""
    # Try artwork array first (albums have cover/jacket images)
    if artwork := data.get("artwork"):
        for art in artwork:
            if art.get("type") == "cover":
                url: str | None = art.get("large") or art.get("img")
                return url
    # Fall back to img field
    result: str | None = data.get("img")
    return result
