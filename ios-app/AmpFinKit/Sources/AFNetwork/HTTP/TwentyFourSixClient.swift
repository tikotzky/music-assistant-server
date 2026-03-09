//
//  TwentyFourSixClient.swift
//  AmpFin
//
//  24six API client replacing JellyfinClient.
//

import Foundation
import AFFoundation
import SwiftUI
import OSLog

@Observable
public final class TwentyFourSixClient {
    public private(set) var _token: String?
    public private(set) var _deviceId: String?
    public private(set) var _deviceSerial: String?

    public private(set) var _email: String?
    public private(set) var _password: String?
    public private(set) var _profileId: String?
    public private(set) var _profilePin: String?

    let logger = Logger(subsystem: "io.rfk.ampfin", category: "HTTP")
    static let defaults = AFKIT_ENABLE_ALL_FEATURES ? UserDefaults(suiteName: AFKIT_APP_GROUP)! : UserDefaults.standard

    public static let baseURL = URL(string: "https://24six.app/api/v3")!
    public static let platformKey = "production-ios-d8225f34"
    public static let apiMinorVersion = "11"
    public static let appVersion = "2.3.8"
    public static let osVersion = "26.1"
    public static let userAgent = "24Six/2.3.8 (app.tfs.prod; build:162; iOS 26.1.0) Alamofire/5.7.1"

    private init(token: String?, deviceId: String?, deviceSerial: String?, email: String?, password: String?, profileId: String?, profilePin: String?) {
        if !AFKIT_ENABLE_ALL_FEATURES {
            logger.warning("User data will not be stored in an app group")
        }

        _token = token
        _deviceId = deviceId
        _deviceSerial = deviceSerial
        _email = email
        _password = password
        _profileId = profileId
        _profilePin = profilePin
    }

    public var online: Bool = false
}

public extension TwentyFourSixClient {
    var authorized: Bool {
        _token != nil
    }

    var token: String {
        _token ?? ""
    }

    var deviceId: String {
        if let id = _deviceId {
            return id
        }
        let id = UUID().uuidString
        store(deviceId: id)
        return id
    }

    var deviceSerial: String {
        if let serial = _deviceSerial {
            return serial
        }
        let serial = UUID().uuidString.uppercased()
        store(deviceSerial: serial)
        return serial
    }
}

// MARK: - Storage

public extension TwentyFourSixClient {
    func store(token: String?) {
        Self.defaults.set(token, forKey: "token")
        _token = token
    }

    func store(deviceId: String?) {
        Self.defaults.set(deviceId, forKey: "deviceId")
        _deviceId = deviceId
    }

    func store(deviceSerial: String?) {
        Self.defaults.set(deviceSerial, forKey: "deviceSerial")
        _deviceSerial = deviceSerial
    }

    func store(email: String?) {
        Self.defaults.set(email, forKey: "email")
        _email = email
    }

    func store(password: String?) {
        Self.defaults.set(password, forKey: "password")
        _password = password
    }

    func store(profileId: String?) {
        Self.defaults.set(profileId, forKey: "profileId")
        _profileId = profileId
    }

    func store(profilePin: String?) {
        Self.defaults.set(profilePin, forKey: "profilePin")
        _profilePin = profilePin
    }

    func logout() {
        store(token: nil)
        store(email: nil)
        store(password: nil)
        store(profileId: nil)
        store(profilePin: nil)
    }
}

// MARK: - Singleton

public extension TwentyFourSixClient {
    static let shared = TwentyFourSixClient(
        token: defaults.string(forKey: "token"),
        deviceId: defaults.string(forKey: "deviceId"),
        deviceSerial: defaults.string(forKey: "deviceSerial"),
        email: defaults.string(forKey: "email"),
        password: defaults.string(forKey: "password"),
        profileId: defaults.string(forKey: "profileId"),
        profilePin: defaults.string(forKey: "profilePin"))
}

// MARK: - Compatibility stubs

public extension TwentyFourSixClient {
    /// Compatibility: clientId maps to deviceId.
    var clientId: String { deviceId }

    /// Compatibility: app version string.
    var clientVersion: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "unknown" }
    var clientBuild: String { Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "unknown" }

    /// Compatibility: custom HTTP headers (not used by 24six, but kept for compilation).
    struct CustomHTTPHeader: Codable {
        public var key: String
        public var value: String

        public init(key: String, value: String) {
            self.key = key
            self.value = value
        }
    }

    var customHTTPHeaders: [CustomHTTPHeader] {
        get { [] }
        set { }
    }

    var customHTTPHeaderDictionary: [String: String] {
        [:]
    }

    /// Generate a session ID for playback (MD5 hash of trackId + bitrate).
    static func sessionID(itemId: String, bitrate: Int?) -> String {
        let input = "\(itemId)::\(bitrate ?? -1)"
        // Simple hash - not cryptographic, just for session tracking
        var hash: UInt64 = 5381
        for byte in input.utf8 {
            hash = ((hash << 5) &+ hash) &+ UInt64(byte)
        }
        return String(format: "%016llx", hash)
    }
}

// MARK: - Typealias for backward compatibility

public typealias JellyfinClient = TwentyFourSixClient
