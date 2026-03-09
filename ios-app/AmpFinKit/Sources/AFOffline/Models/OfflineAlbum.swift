//
//  OfflineAlbum.swift
//  Music
//
//  Created by Rasmus Krämer on 08.09.23.
//

import Foundation
import SwiftData
import AFFoundation

@Model
final class OfflineAlbumV2: OfflineParent {
    @Attribute(.unique)
    var id: String
    var name: String

    var overview: String?
    var genres: [String]

    var released: Date?
    var artists: [Item.OfflineReducedArtist]

    var favorite: Bool
    var lastPlayed: Date?

    var childrenIdentifiers: [String]

    init(id: String, name: String, overview: String?, genres: [String], released: Date?, artists: [Item.OfflineReducedArtist], favorite: Bool, childrenIdentifiers: [String]) {
        self.id = id
        self.name = name
        self.overview = overview
        self.genres = genres
        self.released = released
        self.artists = artists
        self.favorite = favorite
        self.childrenIdentifiers = childrenIdentifiers
    }
}

internal typealias OfflineAlbum = OfflineAlbumV2
