//
//  Cover+Convert.swift
//  AmpFin
//
//  Image URL helper for 24six API responses.
//

import Foundation
import AFFoundation

/// Helper to extract the best image URL from 24six artwork arrays.
enum TFSImageHelper {
    static func bestImageURL(from artwork: [TFSArtwork]?, fallback: String?) -> URL? {
        // Try artwork array first (prefer cover type with large variant)
        if let artwork {
            for art in artwork {
                if art.type == "cover" {
                    if let large = art.large, let url = URL(string: large) {
                        return url
                    }
                    if let img = art.img, let url = URL(string: img) {
                        return url
                    }
                }
            }
            // Any artwork image
            for art in artwork {
                if let large = art.large, let url = URL(string: large) {
                    return url
                }
                if let img = art.img, let url = URL(string: img) {
                    return url
                }
            }
        }

        // Fall back to img field
        if let fallback, let url = URL(string: fallback) {
            return url
        }

        return nil
    }
}
