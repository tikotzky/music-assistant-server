//
//  JellyfinWebSocket.swift
//  MusicKit
//
//  Created by Rasmus Krämer on 24.12.23.
//

import Foundation

/// Stub: 24six does not support WebSocket-based remote sessions.
/// This class is retained as a minimal stub so that existing references compile.
@Observable
public final class JellyfinWebSocket {
    public internal(set) var connected = false

    private init() {}

    public func connect() {
        // 24six does not support WebSocket; no-op
    }

    public func beginObservingSessionUpdated(clientId: String) {
        // no-op
    }

    public func stopObservingSessionUpdated() {
        // no-op
    }
}

public extension JellyfinWebSocket {
    static let shared = JellyfinWebSocket()

    static let disconnectedNotification = NSNotification.Name("io.rfk.ampfin.socket.disconnect")
    static let playCommandIssuedNotification = NSNotification.Name("io.rfk.ampfin.socket.command.play")
    static let playStateCommandIssuedNotification = NSNotification.Name("io.rfk.ampfin.socket.command.playState")
    static let sessionUpdateNotification = NSNotification.Name("io.rfk.ampfin.socket.session.update")
}
