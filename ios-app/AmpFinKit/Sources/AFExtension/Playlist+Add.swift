//
//  Playlist+Add.swift
//  AmpFin
//
//  Add tracks to playlist using 24six API.
//

import Foundation
import AFFoundation
import AFNetwork
#if canImport(AFOffline)
import AFOffline
#endif

public extension Playlist {
    func add(trackIds: [String]) async throws {
        try await TwentyFourSixClient.shared.add(trackIds: trackIds, playlistId: id)

        #if canImport(AFOffline)
        if OfflineManager.shared.offlineStatus(playlistId: id) != .none {
            try await OfflineManager.shared.download(playlist: self)
        }
        #endif

        trackCount = try await TwentyFourSixClient.shared.tracks(playlistId: id).count
    }
}
