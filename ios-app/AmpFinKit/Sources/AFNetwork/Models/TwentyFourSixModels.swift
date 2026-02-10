//
//  TwentyFourSixModels.swift
//  AmpFin
//
//  API response models for the 24six v3 API.
//

import Foundation

// MARK: - Profile List

internal struct ProfileListResponse: Decodable {
    let profiles: [Profile]

    struct Profile: Decodable {
        let id: String
        let name: String
        let pin_required: Bool?
    }
}

// MARK: - Login

internal struct LoginResponse: Decodable {
    let token: String
    let device_id: String?
    let profile: LoginProfile?

    struct LoginProfile: Decodable {
        let id: String?
        let name: String?
    }
}

// MARK: - Paginated Response

internal struct PaginatedResponse<T: Decodable>: Decodable {
    let data: [T]
    let meta: PaginationMeta?
}

internal struct PaginationMeta: Decodable {
    let pagination: PaginationInfo?
}

internal struct PaginationInfo: Decodable {
    let next_page: Int?
    let current_page: Int?
    let per_page: Int?
}

// MARK: - Artist

internal struct TFSArtist: Decodable {
    let id: String
    let name: String?
    let preview_url: String?
    let img: String?
    let is_favorite: Bool?
}

// MARK: - Album / Collection

internal struct TFSCollection: Decodable {
    let id: String
    let title: String?
    let preview_url: String?
    let year: Int?
    let release_date: String?
    let img: String?
    let is_favorite: Bool?
    let artists: [TFSArtist]?
    let artwork: [TFSArtwork]?
    let contents: [TFSContent]?
}

// MARK: - Track / Content

internal struct TFSContent: Decodable {
    let id: String
    let title: String?
    let preview_url: String?
    let length: Double?
    let track_num: Int?
    let disc_num: Int?
    let unplayable: Bool?
    let is_favorite: Bool?
    let artists: [TFSArtist]?
    let collection_id: String?
    let collection: TFSContentCollection?
    let img: String?
    let artwork: [TFSArtwork]?
}

internal struct TFSContentCollection: Decodable {
    let id: String?
    let title: String?
    let artwork: [TFSArtwork]?
}

// MARK: - Playlist

internal struct TFSPlaylist: Decodable {
    let id: String
    let title: String?
    let preview_url: String?
    let img: String?
    let is_favorite: Bool?
    let mine: Bool?
    let profile: TFSPlaylistProfile?
    let contents: [TFSContent]?
}

internal struct TFSPlaylistProfile: Decodable {
    let name: String?
}

// MARK: - Artwork

internal struct TFSArtwork: Decodable {
    let type: String?
    let large: String?
    let img: String?
}

// MARK: - Search

internal struct SearchResponse: Decodable {
    let artists: [TFSArtist]?
    let collections: [TFSCollection]?
    let songs: [TFSContent]?
    let playlists: [TFSPlaylist]?
}

// MARK: - Single item wrappers

internal struct ArtistResponse: Decodable {
    let artist: TFSArtist
}

internal struct CollectionResponse: Decodable {
    let collection: TFSCollection
}

internal struct PlaylistResponse: Decodable {
    let playlist: TFSPlaylist
}

// MARK: - Homepage

internal struct HomepageResponse: Decodable {
    let banners: [TFSBanner]?
    let by24Six: [TFSHomepageSection]?
}

internal struct TFSBanner: Decodable {
    let id: String?
    let title: String?
    let img: String?
    let entity_type: String?
    let entity_id: String?
}

internal struct TFSHomepageSection: Decodable {
    let id: String?
    let title: String?
    let collections: [TFSCollection]?
    let playlists: [TFSPlaylist]?
}

// MARK: - Category

internal struct TFSCategory: Decodable {
    let id: String
    let title: String?
}

internal struct CategoryDetailResponse: Decodable {
    let releases: [TFSCollection]?
}
