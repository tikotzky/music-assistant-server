//
//  TwentyFourSixClient+Track.swift
//  AmpFin
//
//  Track-related methods for 24six API.
//

import Foundation
import AFFoundation

public extension TwentyFourSixClient {
    func tracks(limit: Int, startIndex: Int, sortOrder: ItemSortOrder, ascending: Bool, favoriteOnly: Bool = false, search: String? = nil, coverSize: Cover.CoverSize = .normal) async throws -> ([Track], Int) {
        if let search {
            let results = try await searchAll(query: search, limit: limit)
            return (results.tracks, results.tracks.count)
        }

        var allTracks: [Track] = []
        var page = 1
        let perPage = min(limit > 0 ? limit : 200, 200)

        repeat {
            let query: [URLQueryItem] = [
                URLQueryItem(name: "page", value: String(page)),
                URLQueryItem(name: "per_page", value: String(perPage)),
                URLQueryItem(name: "sort", value: sortOrder.twentyFourSixTrackValue),
                URLQueryItem(name: "library", value: "1"),
                URLQueryItem(name: "no_pagination", value: "0"),
            ]

            let response = try await request(ClientRequest<PaginatedResponse<TFSContent>>(
                path: "music/content",
                method: "GET",
                query: query))

            allTracks.append(contentsOf: response.data.enumerated().compactMap { index, item in
                Track(item, fallbackIndex: startIndex + allTracks.count + index)
            })

            if limit > 0 && allTracks.count >= limit {
                break
            }

            guard response.meta?.pagination?.next_page != nil else { break }
            page += 1
        } while page <= 100

        let result = limit > 0 ? Array(allTracks.prefix(limit)) : allTracks
        return (result, result.count)
    }

    func tracks(albumId identifier: String) async throws -> [Track] {
        let response = try await request(ClientRequest<CollectionResponse>(
            path: "music/collection/\(identifier)",
            method: "GET"))

        guard let contents = response.collection.contents else {
            return []
        }

        return contents.enumerated().compactMap { index, item in
            Track(item, fallbackIndex: index)
        }
    }

    func tracks(playlistId identifier: String) async throws -> [Track] {
        let response = try await request(ClientRequest<PlaylistResponse>(
            path: "music/playlist/\(identifier)",
            method: "GET"))

        guard let contents = response.playlist.contents else {
            return []
        }

        return contents.enumerated().compactMap { index, item in
            Track(item, fallbackIndex: index)
        }
    }

    func tracks(artistId identifier: String, sortOrder: ItemSortOrder, ascending: Bool, limit: Int = 30) async throws -> [Track] {
        let response = try await request(ClientRequest<PaginatedResponse<TFSContent>>(
            path: "music/content",
            method: "GET",
            query: [
                URLQueryItem(name: "page", value: "1"),
                URLQueryItem(name: "per_page", value: String(limit)),
                URLQueryItem(name: "sort", value: sortOrder.twentyFourSixTrackValue),
                URLQueryItem(name: "artist_id", value: identifier),
            ]))

        return response.data.enumerated().compactMap { index, item in
            Track(item, fallbackIndex: index)
        }
    }

    func track(identifier: String) async throws -> Track {
        let response = try await request(ClientRequest<TFSContent>(
            path: "music/content/\(identifier)",
            method: "POST"))

        guard let track = Track(response) else {
            throw ClientError.invalidResponse
        }

        return track
    }

    func tracks(instantMixBaseId identifier: String, limit: Int = 200) async throws -> [Track] {
        // 24six doesn't have an instant mix endpoint - use search with artist of the track
        // Return empty for now; the UI can handle this gracefully
        return []
    }

    func lyrics(trackId identifier: String) async throws -> Track.Lyrics {
        // 24six doesn't expose lyrics via API
        throw ClientError.invalidResponse
    }

    func mediaInfo(trackId identifier: String) async throws -> Track.MediaInfo {
        // 24six streams AAC/M4A
        return .init(codec: "aac", lossless: false, bitrate: nil, bitDepth: nil, sampleRate: nil)
    }

    func streamURL(trackId identifier: String) async throws -> URL {
        try await requestStreamURL(
            path: "content/\(identifier)/play",
            queryItems: [URLQueryItem(name: "format", value: "m4a")])
    }
}
