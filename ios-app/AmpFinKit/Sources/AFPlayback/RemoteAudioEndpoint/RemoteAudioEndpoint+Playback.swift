//
//  File.swift
//
//
//  Created by Rasmus Krämer on 22.05.24.
//

import Foundation
import AVKit
import AFFoundation
import AFNetwork

extension RemoteAudioEndpoint: AudioEndpoint {
    var playing: Bool {
        get {
            _playing
        }
        set {
            // 24six does not support remote sessions; no-op
        }
    }

    var duration: Double {
        nowPlaying?.runtime ?? 0
    }
    var currentTime: Double {
        get {
            _currentTime
        }
        set {
            Task {
                await seek(to: newValue)
            }
        }
    }

    var shuffled: Bool {
        get {
            _shuffled
        }
        set {
            _shuffled = newValue
            // 24six does not support remote sessions; no-op
        }
    }
    var repeatMode: RepeatMode {
        get {
            _repeatMode
        }
        set {
            _repeatMode = newValue
            // 24six does not support remote sessions; no-op
        }
    }

    public var volume: Float {
        get {
            _volume
        }
        set {
            // 24six does not support remote sessions; no-op
        }
    }

    var mediaInfo: Track.MediaInfo? {
        get async {
            // 24six does not support remote session media info; return stub AAC info
            return .init(codec: "AAC", lossless: false, bitrate: nil, bitDepth: nil, sampleRate: nil)
        }
    }

    func seek(to seconds: Double) async {
        // 24six does not support remote sessions; no-op
    }

    func startPlayback(tracks: [Track], startIndex: Int, shuffle: Bool) {
        // 24six does not support remote sessions; no-op
    }

    func stopPlayback() {
        // 24six does not support remote sessions; no-op
    }

    func advance() {
        NotificationCenter.default.post(name: AudioPlayer.forwardsNotification, object: nil)
    }

    func rewind() {
        NotificationCenter.default.post(name: AudioPlayer.backwardsNotification, object: nil)
    }

    func queue(_ track: Track, after index: Int, updateUnalteredQueue: Bool) {
        // 24six does not support remote sessions; no-op
    }

    func queue(_ tracks: [Track], after index: Int) {
        // 24six does not support remote sessions; no-op
    }

    // 24six does not support remote sessions

    var queue: [Track] { [] }
    var infiniteQueue: [Track]? { nil }
    var history: [Track] { [] }
    var buffering: Bool { false }
    var outputRoute: AudioPlayer.AudioRoute { .init(port: .virtual, name: clientId) }
    var allowQueueLater: Bool { true }

    func skip(to: Int) {}
    func remove(at index: Int) -> Track? { nil }
    func removePlayed(at index: Int) {}
    func move(from index: Int, to destination: Int) {}
    func restorePlayed(upTo index: Int) {}
}
