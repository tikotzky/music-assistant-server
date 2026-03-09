//
//  TwentyFourSixClient+Playlist.swift
//  AmpFin
//
//  Playlist-related methods for 24six API.
//

import Foundation
import AFFoundation

public extension TwentyFourSixClient {
    func create(playlistName: String, trackIds: [String], isPublic: Bool) async throws {
        // Step 1: Create the playlist
        var query: [URLQueryItem] = [
            URLQueryItem(name: "name", value: playlistName),
        ]

        let response = try await request(ClientRequest<PlaylistResponse>(
            path: "music/playlist",
            method: "POST",
            query: query))

        // Step 2: Add tracks if any
        if !trackIds.isEmpty {
            var addQuery: [URLQueryItem] = trackIds.map {
                URLQueryItem(name: "content[]", value: $0)
            }
            addQuery.append(URLQueryItem(name: "force", value: "1"))

            let _ = try await request(ClientRequest<EmptyResponse>(
                path: "music/playlist/\(response.playlist.id.value)/add",
                method: "POST",
                query: addQuery))
        }
    }

    func playlists(limit: Int, sortOrder: ItemSortOrder, ascending: Bool, favoriteOnly: Bool = false, search: String? = nil) async throws -> [Playlist] {
        if let search {
            let results = try await searchAll(query: search, limit: limit)
            return results.playlists
        }

        var allPlaylists: [Playlist] = []
        var page = 1
        let perPage = min(limit > 0 ? limit : 200, 200)

        repeat {
            var query: [URLQueryItem] = [
                URLQueryItem(name: "page", value: String(page)),
                URLQueryItem(name: "per_page", value: String(perPage)),
                URLQueryItem(name: "sort", value: "alpha"),
                URLQueryItem(name: "library", value: "1"),
            ]

            let response = try await request(ClientRequest<PaginatedResponse<TFSPlaylist>>(
                path: "music/playlist",
                method: "GET",
                query: query))

            allPlaylists.append(contentsOf: response.data.map(Playlist.init))

            if limit > 0 && allPlaylists.count >= limit {
                break
            }

            guard response.meta?.pagination?.next_page != nil else { break }
            page += 1
        } while page <= 100

        return limit > 0 ? Array(allPlaylists.prefix(limit)) : allPlaylists
    }

    func playlist(identifier: String) async throws -> Playlist {
        let response = try await request(ClientRequest<PlaylistResponse>(
            path: "music/playlist/\(identifier)",
            method: "GET"))

        return Playlist(response.playlist)
    }

    func add(trackIds: [String], playlistId: String) async throws {
        var query: [URLQueryItem] = trackIds.map {
            URLQueryItem(name: "content[]", value: $0)
        }
        query.append(URLQueryItem(name: "force", value: "1"))

        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "music/playlist/\(playlistId)/add",
            method: "POST",
            query: query))
    }

    func remove(trackId: String, playlistId: String) async throws {
        // Fetch current playlist tracks, rebuild without the target
        let playlistResp = try await request(ClientRequest<PlaylistResponse>(
            path: "music/playlist/\(playlistId)",
            method: "GET"))

        guard let contents = playlistResp.playlist.contents else {
            throw ClientError.parseFailed
        }

        let remainingIds = contents.filter { $0.id.value != trackId }.map { $0.id.value }

        var query: [URLQueryItem] = remainingIds.map {
            URLQueryItem(name: "content[]", value: $0)
        }
        query.append(URLQueryItem(name: "force", value: "1"))

        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "music/playlist/\(playlistId)",
            method: "PATCH",
            query: query))
    }

    func move(trackId: String, index: Int, playlistId: String) async throws {
        // Fetch current playlist, reorder, then PATCH
        let playlistResp = try await request(ClientRequest<PlaylistResponse>(
            path: "music/playlist/\(playlistId)",
            method: "GET"))

        guard var contents = playlistResp.playlist.contents else {
            throw ClientError.parseFailed
        }

        guard let currentIndex = contents.firstIndex(where: { $0.id.value == trackId }) else {
            throw ClientError.parseFailed
        }

        let item = contents.remove(at: currentIndex)
        let targetIndex = min(index, contents.count)
        contents.insert(item, at: targetIndex)

        var query: [URLQueryItem] = contents.map {
            URLQueryItem(name: "content[]", value: $0.id.value)
        }
        query.append(URLQueryItem(name: "force", value: "1"))

        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "music/playlist/\(playlistId)",
            method: "PATCH",
            query: query))
    }
}
