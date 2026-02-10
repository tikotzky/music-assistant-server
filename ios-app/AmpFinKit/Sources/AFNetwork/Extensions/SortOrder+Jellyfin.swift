//
//  SortOrder+TwentyFourSix.swift
//  AmpFin
//
//  Map ItemSortOrder to 24six API sort parameter values.
//

import Foundation
import AFFoundation

internal extension ItemSortOrder {
    /// Sort value for album/collection endpoints.
    var twentyFourSixAlbumValue: String {
        switch self {
        case .name:
            "alpha"
        case .added, .lastPlayed:
            "recent"
        case .plays, .random:
            "popular"
        case .released:
            "newAlbums"
        default:
            "popular"
        }
    }

    /// Sort value for track/content endpoints.
    var twentyFourSixTrackValue: String {
        switch self {
        case .name:
            "alpha"
        case .plays, .random:
            "popular"
        default:
            "popular"
        }
    }

    /// Sort value for artist endpoints.
    var twentyFourSixArtistValue: String {
        switch self {
        case .name:
            "alpha"
        case .plays, .random:
            "popular"
        case .added, .lastPlayed:
            "recent"
        default:
            "alpha"
        }
    }
}
