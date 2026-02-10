//
//  TwentyFourSixClient+Progress.swift
//  AmpFin
//
//  Playback progress reporting for 24six API.
//

import Foundation
import AFFoundation

public extension TwentyFourSixClient {
    func playbackStarted(identifier: String, queueIds: [String]) async throws {
        // 24six uses a simple log endpoint; report start at position 0
        try await logPlayback(trackId: identifier, current: 0, seconds: 0)
    }

    func progress(identifier: String, position: Double, paused: Bool, repeatMode: RepeatMode, shuffled: Bool, volume: Float) async throws {
        let seconds = Int(position)
        try await logPlayback(trackId: identifier, current: seconds, seconds: seconds)
    }

    func playbackStopped(identifier: String, positionSeconds: Double, playSessionId: String?) async throws {
        let seconds = Int(positionSeconds)
        try await logPlayback(trackId: identifier, current: seconds, seconds: seconds)
    }

    private func logPlayback(trackId: String, current: Int, seconds: Int) async throws {
        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "content/\(trackId)/log",
            method: "POST",
            query: [
                URLQueryItem(name: "current", value: String(current)),
                URLQueryItem(name: "seconds", value: String(seconds)),
                URLQueryItem(name: "device_id", value: deviceId),
                URLQueryItem(name: "is_offline", value: "0"),
            ]))
    }
}
