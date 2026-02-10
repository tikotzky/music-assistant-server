//
//  TwentyFourSixClient+Search.swift
//  AmpFin
//
//  Search functionality for 24six API.
//

import Foundation
import AFFoundation

public extension TwentyFourSixClient {
    struct SearchResults {
        public let artists: [Artist]
        public let albums: [Album]
        public let tracks: [Track]
        public let playlists: [Playlist]
    }

    func searchAll(query: String, limit: Int = 20) async throws -> SearchResults {
        let response = try await request(ClientRequest<SearchResponse>(
            path: "music/search",
            method: "POST",
            query: [
                URLQueryItem(name: "q", value: query),
                URLQueryItem(name: "limit", value: String(limit)),
            ]))

        let artists = (response.artists ?? []).map(Artist.init)
        let albums = (response.collections ?? []).map(Album.init)
        let tracks = (response.songs ?? []).enumerated().compactMap { index, item in
            Track(item, fallbackIndex: index)
        }
        let playlists = (response.playlists ?? []).map(Playlist.init)

        return SearchResults(artists: artists, albums: albums, tracks: tracks, playlists: playlists)
    }
}
