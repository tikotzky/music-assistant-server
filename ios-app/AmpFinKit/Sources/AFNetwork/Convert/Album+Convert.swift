//
//  Album+Convert.swift
//  AmpFin
//
//  Convert 24six TFSCollection to Album model.
//

import Foundation
import AFFoundation

internal extension Album {
    convenience init(_ from: TFSCollection) {
        var cover: Cover?
        if let imageURL = TFSImageHelper.bestImageURL(from: from.artwork, fallback: from.img) {
            cover = Cover(type: .remote, size: .normal, url: imageURL)
        }

        var releaseDate: Date?
        if let dateStr = from.release_date {
            releaseDate = Date(dateStr)
        }

        self.init(
            id: from.id.value,
            name: from.title ?? "Unknown Album",
            cover: cover,
            favorite: from.is_favorite ?? false,
            overview: nil,
            genres: [],
            releaseDate: releaseDate,
            artists: from.artists?.map { ReducedArtist(id: $0.id.value, name: $0.name ?? "Unknown") } ?? [],
            playCount: 0,
            lastPlayed: nil)
    }
}
