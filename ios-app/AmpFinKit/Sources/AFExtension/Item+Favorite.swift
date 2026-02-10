//
//  Item+Favorite.swift
//  AmpFin
//
//  Favorite toggle using 24six API.
//

import Foundation
import AFFoundation
import AFNetwork

#if canImport(AFOffline)
import AFOffline
#endif

public extension Item {
    var favorite: Bool {
        get {
            _favorite
        }
        set {
            #if canImport(AFOffline)
            _favorite = newValue

            OfflineManager.shared.update(favorite: newValue, itemId: self.id)

            Task {
                do {
                    try await TwentyFourSixClient.shared.favorite(newValue, identifier: self.id)
                } catch {
                    OfflineManager.shared.cache(favorite: newValue, itemId: self.id)
                }
            }
            #else
            Task {
                do {
                    try await TwentyFourSixClient.shared.favorite(newValue, identifier: self.id)
                    _favorite = newValue
                } catch {}
            }
            #endif

            NotificationCenter.default.post(name: Self.affinityChangedNotification, object: id, userInfo: [
                "favorite": newValue,
            ])
        }
    }
}
