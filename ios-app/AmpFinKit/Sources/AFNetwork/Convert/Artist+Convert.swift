//
//  Artist+Convert.swift
//  AmpFin
//
//  Convert 24six TFSArtist to Artist model.
//

import Foundation
import AFFoundation

internal extension Artist {
    convenience init(_ from: TFSArtist) {
        var cover: Cover?
        if let imgStr = from.img, let imageURL = URL(string: imgStr) {
            cover = Cover(type: .remote, size: .normal, url: imageURL)
        }

        self.init(
            id: from.id,
            name: from.name ?? "Unknown Artist",
            cover: cover,
            favorite: from.is_favorite ?? false,
            overview: nil)
    }
}
