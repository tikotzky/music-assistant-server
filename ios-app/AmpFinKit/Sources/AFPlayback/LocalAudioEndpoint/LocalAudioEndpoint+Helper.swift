//
//  LocalAudioEndpoint+Helper.swift
//  AmpFin
//
//  Playback helper for 24six streaming.
//

import Foundation
import Network
import AVKit
import Defaults

import AFFoundation
import AFNetwork

#if canImport(AFOffline)
import AFOffline
#endif

internal extension LocalAudioEndpoint {
    func avPlayerItem(track: Track) -> AVPlayerItem {
        #if canImport(AFOffline)
        if DownloadManager.shared.downloaded(trackId: track.id) {
            return AVPlayerItem(url: DownloadManager.shared.url(trackId: track.id))
        }
        #endif

        // For 24six, we need to resolve the stream URL first.
        // Since AVPlayerItem needs a URL synchronously, we use a placeholder
        // and the actual stream URL resolution happens in the playback flow.
        // The stream URL is fetched via the 24six API redirect mechanism.
        let streamURL = TwentyFourSixClient.baseURL
            .appending(path: "content")
            .appending(path: track.id)
            .appending(path: "play")
            .appending(queryItems: [
                URLQueryItem(name: "format", value: "m4a"),
            ])

        // Build headers for authentication
        var headers: [String: String] = [
            "Authorization": "Bearer \(TwentyFourSixClient.shared.token)",
            "X-Platform-Key": TwentyFourSixClient.platformKey,
            "X-API-MINOR-VERSION": TwentyFourSixClient.apiMinorVersion,
            "app-version": TwentyFourSixClient.appVersion,
            "os": "iOS",
            "os-version": TwentyFourSixClient.osVersion,
            "User-Agent": TwentyFourSixClient.userAgent,
            "X-DEVICE-ID": TwentyFourSixClient.shared.deviceId,
            "X-DEVICE-SERIAL": TwentyFourSixClient.shared.deviceSerial,
        ]

        let asset = AVURLAsset(url: streamURL, options: [
            "AVURLAssetHTTPHeaderFieldsKey": headers,
        ])

        return AVPlayerItem(asset: asset)
    }

    func avPlayerItemAsync(track: Track) async -> AVPlayerItem {
        #if canImport(AFOffline)
        if DownloadManager.shared.downloaded(trackId: track.id) {
            return AVPlayerItem(url: DownloadManager.shared.url(trackId: track.id))
        }
        #endif

        // Try to resolve the actual stream URL via the redirect
        if let resolvedURL = try? await TwentyFourSixClient.shared.streamURL(trackId: track.id) {
            return AVPlayerItem(url: resolvedURL)
        }

        // Fallback to direct URL with auth headers
        return avPlayerItem(track: track)
    }

    func populateAVPlayerQueue() {
        guard let nowPlaying else {
            return
        }

        var expected = [nowPlaying]

        let candidates = queue.prefix(4) + infiniteQueue!.prefix(4)
        expected += candidates.prefix(4)


        if audioPlayer.items().count > avPlayerQueue.count {
            logger.warning("AVQueuePlayer queue contains more (\(self.audioPlayer.items().count)) items than expected (\(self.avPlayerQueue.count))")
        }

        var firstOutdatedIndex = -1

        // Find the first index where a mismatch occurs
        for (index, track) in expected.enumerated() {
            guard avPlayerQueue.count > index else {
                // Queue was shorter and has to be extended
                firstOutdatedIndex = index
                break
            }

            if avPlayerQueue[index] == track.id {
                continue
            }

            firstOutdatedIndex = index
            break
        }

        logger.info("AVQueuePlayer queue outdated starting from \(firstOutdatedIndex == -1 ? "-" : String(firstOutdatedIndex + 1)) / \(self.avPlayerQueue.count) [\(expected.count) expected]")

        guard firstOutdatedIndex > -1 else {
            return
        }

        // Remove outdated tracks
        while firstOutdatedIndex < avPlayerQueue.count {
            guard let last = audioPlayer.items().last else {
                break
            }

            audioPlayer.remove(last)
            avPlayerQueue.removeLast()
        }

        // Fill queue
        for track in expected[firstOutdatedIndex..<expected.count] {
            audioPlayer.insert(avPlayerItem(track: track), after: nil)
            avPlayerQueue.append(track.id)
        }
    }

    func determineBitrate() {
        let currentPath = networkMonitor.currentPath
        let bitrate: Int

        if currentPath.isExpensive || currentPath.isConstrained {
            bitrate = Defaults[.maxConstrainedBitrate]
        } else {
            bitrate = Defaults[.maxStreamingBitrate]
        }

        if bitrate <= 0 {
            maxBitrate = nil
        } else {
            maxBitrate = bitrate
        }
    }
    func setupNetworkPathMonitor() {
        networkMonitor.pathUpdateHandler = { [weak self] networkPath in
            guard let self = self else {
                return
            }

            switch networkPath.status {
                case .satisfied:
                    determineBitrate()
                default:
                    maxBitrate = nil
            }
        }

        networkMonitor.start(queue: DispatchQueue.global(qos: .userInitiated))
    }

    func updatePlaybackReporter(scheduled: Bool) {
        playbackReporter?.update(
            positionSeconds: currentTime,
            paused: !playing,
            repeatMode: repeatMode,
            shuffled: shuffled,
            volume: volume,
            scheduled: scheduled)
    }
}
