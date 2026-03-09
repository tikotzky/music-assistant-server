//
//  Playlist+Convert.swift
//  AmpFin
//
//  Convert 24six TFSPlaylist to Playlist model.
//

import Foundation
import AFFoundation

internal extension Playlist {
    convenience init(_ from: TFSPlaylist) {
        var cover: Cover?
        if let imgStr = from.img, let imageURL = URL(string: imgStr) {
            cover = Cover(type: .remote, size: .normal, url: imageURL)
        }

        let trackCount = from.contents?.count ?? 0
        let duration = from.contents?.reduce(0.0) { $0 + ($1.length ?? 0) } ?? 0

        self.init(
            id: from.id.value,
            name: from.title ?? "Unknown Playlist",
            cover: cover,
            favorite: from.is_favorite ?? false,
            duration: duration,
            trackCount: trackCount)
    }
}
