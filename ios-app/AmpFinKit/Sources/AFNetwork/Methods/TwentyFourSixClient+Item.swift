//
//  TwentyFourSixClient+Item.swift
//  AmpFin
//
//  Item-level operations for 24six API (favorites, library, delete).
//

import Foundation

public extension TwentyFourSixClient {
    func delete(identifier: String) async throws {
        // 24six: only playlists can be deleted (owned)
        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "music/playlist/\(identifier)",
            method: "DELETE"))
    }

    func favorite(_ favorite: Bool, identifier: String) async throws {
        // Try content first, then collection, then artist
        // The 24six API uses different paths per type, but callers don't always know the type
        // We try content (track) first since it's most common
        let types = ["content", "collection", "artist"]
        var lastError: Error?

        for type in types {
            do {
                let _ = try await request(ClientRequest<EmptyResponse>(
                    path: "music/\(type)/\(identifier)/favorite",
                    method: favorite ? "POST" : "DELETE"))
                return
            } catch {
                lastError = error
                continue
            }
        }

        if let lastError {
            throw lastError
        }
    }

    func addToLibrary(type: String, identifier: String) async throws {
        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "music/library/\(type)/\(identifier)",
            method: "POST"))
    }

    func removeFromLibrary(type: String, identifier: String) async throws {
        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "music/library/\(type)/\(identifier)",
            method: "DELETE"))
    }
}
