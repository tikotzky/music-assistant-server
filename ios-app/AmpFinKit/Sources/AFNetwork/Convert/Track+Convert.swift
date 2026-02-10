//
//  Track+Convert.swift
//  AmpFin
//
//  Convert 24six TFSContent to Track model.
//

import Foundation
import AFFoundation

internal extension Track {
    convenience init?(_ from: TFSContent, fallbackIndex: Int = 0, coverSize: Cover.CoverSize = .normal) {
        let albumId = from.collection_id ?? from.collection?.id ?? ""

        var cover: Cover?
        if let imageURL = TFSImageHelper.bestImageURL(from: from.artwork, fallback: from.img) {
            cover = Cover(type: .remote, size: coverSize, url: imageURL)
        } else if let collectionArtwork = from.collection?.artwork, let imageURL = TFSImageHelper.bestImageURL(from: collectionArtwork, fallback: nil) {
            cover = Cover(type: .remote, size: coverSize, url: imageURL)
        }

        let runtime = from.length ?? 0

        let albumName = from.collection?.title
        let albumArtists = from.artists?.map { ReducedArtist(id: $0.id, name: $0.name ?? "Unknown") } ?? []

        self.init(
            id: from.id,
            name: from.title ?? "Unknown Track",
            cover: cover,
            favorite: from.is_favorite ?? false,
            album: ReducedAlbum(
                id: albumId,
                name: albumName,
                artists: albumArtists
            ),
            artists: from.artists?.map { ReducedArtist(id: $0.id, name: $0.name ?? "Unknown") } ?? [],
            lufs: nil,
            index: Index(index: from.track_num ?? fallbackIndex, disk: from.disc_num ?? 1),
            runtime: runtime,
            playCount: 0,
            releaseDate: nil)
    }
}
