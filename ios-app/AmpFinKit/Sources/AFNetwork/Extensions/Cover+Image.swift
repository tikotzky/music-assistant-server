//
//  Cover+Image.swift
//  AmpFin
//
//  Cover image loading for 24six (direct URLs, no custom headers needed).
//

import Foundation
import AFFoundation

#if canImport(UIKit)
import UIKit
#endif

public extension Cover {
    var systemImage: PlatformImage? {
        get async {
            // 24six image URLs are direct HTTPS URLs - no custom headers needed
            guard let (data, _) = try? await URLSession.shared.data(from: url) else {
                return nil
            }

            return PlatformImage(data: data)
        }
    }

    #if canImport(UIKit)
    typealias PlatformImage = UIImage
    #endif
}
