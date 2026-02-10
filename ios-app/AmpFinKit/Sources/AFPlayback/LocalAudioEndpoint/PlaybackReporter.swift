//
//  PlaybackReporter.swift
//  AmpFin
//
//  Reports playback progress to 24six API.
//

import Foundation
import SwiftData
import OSLog
import AFFoundation
import AFNetwork

#if canImport(AFOffline)
import AFOffline
#endif

public final class PlaybackReporter {
    let trackId: String
    var playSessionId: String

    var currentTime: Double = 0

    init(trackId: String, playSessionId: String, queue: [Track]) {
        self.trackId = trackId
        self.playSessionId = playSessionId

        Task {
            try? await TwentyFourSixClient.shared.playbackStarted(identifier: trackId, queueIds: queue.map { $0.id })
        }
    }
    deinit {
        PlaybackReporter.playbackStopped(trackId: trackId, currentTime: currentTime, playSessionId: playSessionId)
    }

    func update(positionSeconds: Double, paused: Bool, repeatMode: RepeatMode, shuffled: Bool, volume: Float, scheduled: Bool) {
        guard positionSeconds.isFinite && !positionSeconds.isNaN && positionSeconds > 0 else {
            return
        }

        currentTime = positionSeconds

        if scheduled {
            if paused {
                return
            }

            if Int(positionSeconds) % 20 != 0 {
                return
            }
        }

        Task {
            try? await TwentyFourSixClient.shared.progress(
                identifier: trackId,
                position: currentTime,
                paused: paused,
                repeatMode: repeatMode,
                shuffled: shuffled,
                volume: volume)
        }
    }
}

extension PlaybackReporter {
    static func playbackStopped(trackId: String, currentTime: Double, playSessionId: String?) {
        Task {
            do {
                try await TwentyFourSixClient.shared.playbackStopped(identifier: trackId, positionSeconds: currentTime, playSessionId: playSessionId)
            } catch {
                #if canImport(AFOffline)
                OfflineManager.shared.cache(position: currentTime, trackId: trackId)
                #endif
            }
        }
    }
}
