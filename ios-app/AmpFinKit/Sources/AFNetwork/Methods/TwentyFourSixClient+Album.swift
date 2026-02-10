//
//  TwentyFourSixClient+Album.swift
//  AmpFin
//
//  Album-related methods for 24six API.
//

import Foundation
import AFFoundation

public extension TwentyFourSixClient {
    func albums(limit: Int, startIndex: Int, sortOrder: ItemSortOrder, ascending: Bool, favoriteOnly: Bool = false, artistId: String? = nil, search: String? = nil) async throws -> ([Album], Int) {
        if let search {
            let results = try await searchAll(query: search, limit: limit)
            return (results.albums, results.albums.count)
        }

        var allAlbums: [Album] = []
        var page = max(1, (startIndex / 200) + 1)
        let perPage = min(limit > 0 ? limit : 200, 200)

        repeat {
            var query: [URLQueryItem] = [
                URLQueryItem(name: "page", value: String(page)),
                URLQueryItem(name: "per_page", value: String(perPage)),
                URLQueryItem(name: "sort", value: sortOrder.twentyFourSixAlbumValue),
            ]

            if favoriteOnly {
                query.append(URLQueryItem(name: "library", value: "1"))
            }

            if let artistId {
                query.append(URLQueryItem(name: "artist_id", value: artistId))
            }

            let response = try await request(ClientRequest<PaginatedResponse<TFSCollection>>(
                path: "music/collection",
                method: "GET",
                query: query))

            allAlbums.append(contentsOf: response.data.map(Album.init))

            if limit > 0 && allAlbums.count >= limit {
                break
            }

            guard response.meta?.pagination?.next_page != nil else { break }
            page += 1
        } while page <= 100

        let result = limit > 0 ? Array(allAlbums.prefix(limit)) : allAlbums
        return (result, result.count)
    }

    func albums(similarToAlbumId albumId: String) async throws -> [Album] {
        // 24six doesn't have a similar albums endpoint
        return []
    }

    func album(identifier: String) async throws -> Album {
        let response = try await request(ClientRequest<CollectionResponse>(
            path: "music/collection/\(identifier)",
            method: "GET"))

        return Album(response.collection)
    }
}
