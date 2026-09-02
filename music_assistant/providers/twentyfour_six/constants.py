"""Constants for the 24six music provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# Base URL for the v3 mobile API
API_BASE_URL: Final[str] = "https://24six.app/api/v3"

# Mobile API platform key (iOS app)
API_PLATFORM_KEY: Final[str] = "production-ios-d8225f34"

# App version headers (mimic the iOS app)
API_MINOR_VERSION: Final[str] = "11"
API_APP_VERSION: Final[str] = "2.3.8"
API_OS_VERSION: Final[str] = "26.1"
API_USER_AGENT: Final[str] = "24Six/2.3.8 (app.tfs.prod; build:162; iOS 26.1.0) Alamofire/5.7.1"

# Content types (the first path segment of most catalog endpoints)
CONTENT_TYPE_MUSIC: Final[str] = "music"
CONTENT_TYPE_PODCAST: Final[str] = "podcast"

# Entity types as used in the API's type fields and library/favorite endpoints
ENTITY_ARTIST: Final[str] = "artist"
ENTITY_COLLECTION: Final[str] = "collection"
ENTITY_CONTENT: Final[str] = "content"
ENTITY_PLAYLIST: Final[str] = "playlist"
ENTITY_RADIO: Final[str] = "radio"

# Stream format requested when the content does not declare its own audio format
DEFAULT_AUDIO_FORMAT: Final[str] = "m4a"
HLS_AUDIO_FORMAT: Final[str] = "m3u8"

# Setup data keys (collected by the setup flow, stored encrypted where secret)
CONF_EMAIL: Final[str] = "twentyfour_six_email"
CONF_PASSWORD: Final[str] = "twentyfour_six_password"
CONF_PROFILE_ID: Final[str] = "twentyfour_six_profile_id"
CONF_PROFILE_PIN: Final[str] = "twentyfour_six_profile_pin"
CONF_SESSION_DATA: Final[str] = "twentyfour_six_session_data"
CONF_DEVICE_ID: Final[str] = "twentyfour_six_device_id"
CONF_DEVICE_SERIAL: Final[str] = "twentyfour_six_device_serial"

# Maximum pages to fetch from a paginated listing (guards against a runaway loop)
MAX_PAGES: Final[int] = 500
# Items per page for paginated listings
PAGE_SIZE: Final[int] = 200
# Items fetched for a recommendation row served by a listing endpoint
RECOMMENDATION_ROW_SIZE: Final[int] = 50
# Most popular tracks returned for an artist
TOP_TRACKS_LIMIT: Final[int] = 50
# Albums listed when browsing a category or the stories (some hold thousands)
BROWSE_LIST_LIMIT: Final[int] = 400
# Seconds until the first now-playing refresh of a playing radio station
RADIO_METADATA_INTERVAL: Final[int] = 20
# Longest wait between now-playing refreshes, even when a long track is playing
RADIO_METADATA_MAX_INTERVAL: Final[int] = 300
# Fraction of an episode that must be played before it counts as fully played
FULLY_PLAYED_THRESHOLD: Final[float] = 0.95
# Timestamp format of the play log, as the app sends it (UTC)
STREAMED_AT_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

# stories are albums of (children's) audio stories, listed with their own sort
STORIES_PARAMS: Final[dict[str, str]] = {"sort": "newStories", "with_contents": "0"}


@dataclass(frozen=True)
class RecommendationRow:
    """A recommendation row: where its items come from and how it is presented."""

    name: str
    translation_key: str
    icon: str
    content_type: str = CONTENT_TYPE_MUSIC
    # key of the content type's (cached) dashboard payload, the app's home screen rows
    dashboard_key: str = ""
    # or a dedicated listing endpoint with its params
    endpoint: str = ""
    params: dict[str, str] = field(default_factory=dict)
    # the profile permission (allowed map key) needed to show the row
    permission: str = CONTENT_TYPE_MUSIC


# row id -> row; the ids are stable, the frontend stores user preferences keyed on them
RECOMMENDATION_ROWS: Final[dict[str, RecommendationRow]] = {
    "banners": RecommendationRow("Featured", "featured", "mdi-star", dashboard_key="banners"),
    "by24Six": RecommendationRow(
        "24six Presents", "presents", "mdi-creation", dashboard_key="by24Six"
    ),
    "releases": RecommendationRow(
        "New Releases", "new_releases", "mdi-new-box", dashboard_key="releases"
    ),
    "trending": RecommendationRow(
        "Trending Tracks", "trending", "mdi-fire", dashboard_key="trending"
    ),
    "recent": RecommendationRow(
        "Recently Played", "recently_played", "mdi-history", dashboard_key="recent"
    ),
    "newAlbums": RecommendationRow(
        "New Albums", "new_albums", "mdi-album", dashboard_key="newAlbums"
    ),
    "newSingles": RecommendationRow(
        "New Singles", "new_singles", "mdi-music-note", dashboard_key="newSingles"
    ),
    "newStories": RecommendationRow(
        "New Stories", "new_stories", "mdi-book-open-page-variant", dashboard_key="newStories"
    ),
    "playlists": RecommendationRow(
        "24six Playlists", "playlists", "mdi-playlist-music", dashboard_key="playlists"
    ),
    "artists": RecommendationRow(
        "Popular Artists", "popular_artists", "mdi-account-music", dashboard_key="artists"
    ),
    "newArtists": RecommendationRow(
        "New Artists", "new_artists", "mdi-account-star", dashboard_key="newArtists"
    ),
    "continueListening": RecommendationRow(
        "Continue Listening",
        "continue_listening",
        "mdi-play-circle-outline",
        content_type=CONTENT_TYPE_PODCAST,
        endpoint=f"{CONTENT_TYPE_PODCAST}/content",
        params={"in_progress": "1", "no_pagination": "0"},
        permission=CONTENT_TYPE_PODCAST,
    ),
    "popularPodcasts": RecommendationRow(
        "Popular Podcasts",
        "popular_podcasts",
        "mdi-podcast",
        content_type=CONTENT_TYPE_PODCAST,
        dashboard_key="popular",
        permission=CONTENT_TYPE_PODCAST,
    ),
    "trendingEpisodes": RecommendationRow(
        "Trending Episodes",
        "trending_episodes",
        "mdi-microphone",
        content_type=CONTENT_TYPE_PODCAST,
        dashboard_key="trending",
        permission=CONTENT_TYPE_PODCAST,
    ),
    "newPodcasts": RecommendationRow(
        "New Podcast Episodes",
        "new_podcast_episodes",
        "mdi-podcast",
        content_type=CONTENT_TYPE_PODCAST,
        endpoint=f"{CONTENT_TYPE_PODCAST}/content",
        params={"sort": "newest", "no_pagination": "0"},
        permission=CONTENT_TYPE_PODCAST,
    ),
}
