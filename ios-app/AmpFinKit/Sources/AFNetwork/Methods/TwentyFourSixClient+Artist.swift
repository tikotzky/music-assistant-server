//
//  TwentyFourSixClient+Artist.swift
//  AmpFin
//
//  Artist-related methods for 24six API.
//

import Foundation
import AFFoundation

public extension TwentyFourSixClient {
    func artists(limit: Int, startIndex: Int, albumOnly: Bool, search: String?) async throws -> ([Artist], Int) {
        if let search {
            let results = try await searchAll(query: search, limit: limit)
            return (results.artists, results.artists.count)
        }

        var allArtists: [Artist] = []
        var page = max(1, (startIndex / 200) + 1)
        let perPage = min(limit > 0 ? limit : 200, 200)

        repeat {
            let query: [URLQueryItem] = [
                URLQueryItem(name: "page", value: String(page)),
                URLQueryItem(name: "per_page", value: String(perPage)),
                URLQueryItem(name: "sort", value: "alpha"),
                URLQueryItem(name: "library", value: "1"),
            ]

            let response = try await request(ClientRequest<PaginatedResponse<TFSArtist>>(
                path: "music/artist",
                method: "GET",
                query: query))

            allArtists.append(contentsOf: response.data.map(Artist.init))

            if limit > 0 && allArtists.count >= limit {
                break
            }

            guard response.meta?.pagination?.next_page != nil else { break }
            page += 1
        } while page <= 100

        let result = limit > 0 ? Array(allArtists.prefix(limit)) : allArtists
        return (result, result.count)
    }

    func artists(search: String) async throws -> [Artist] {
        let results = try await searchAll(query: search, limit: 20)
        return results.artists
    }

    func artist(identifier: String) async throws -> Artist {
        let response = try await request(ClientRequest<ArtistResponse>(
            path: "music/artist/\(identifier)",
            method: "GET"))

        return Artist(response.artist)
    }
}
