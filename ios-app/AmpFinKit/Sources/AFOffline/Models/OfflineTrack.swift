//
//  OfflineTrack.swift
//  Music
//
//  Created by Rasmus Krämer on 08.09.23.
//

import Foundation
import SwiftData
import AFFoundation

@Model
final internal class OfflineTrackV2 {
    @Attribute(.unique)
    var id: String
    var name: String

    var released: Date?

    var album: Track.OfflineReducedAlbum
    var artists: [Item.OfflineReducedArtist]

    var favorite: Bool
    var runtime: Double

    var container: Container!
    var downloadId: Int?

    var lastPlayed: Date?

    init(id: String, name: String, released: Date?, album: Track.OfflineReducedAlbum, artists: [Item.OfflineReducedArtist], favorite: Bool, runtime: Double, downloadId: Int? = nil) {
        self.id = id
        self.name = name
        self.released = released
        self.album = album
        self.artists = artists
        self.favorite = favorite
        self.downloadId = downloadId
        self.runtime = runtime

        container = nil
    }
}

internal extension OfflineTrackV2 {
    enum Container: String, Codable {
        case aac = "aac"
        case m4a = "m4a"
        case mp3 = "mp3"
        case wav = "wav"
        case aiff = "aiff"
        case flac = "flac"
        case webma = "webma"
    }
}

internal typealias OfflineTrack = OfflineTrackV2
