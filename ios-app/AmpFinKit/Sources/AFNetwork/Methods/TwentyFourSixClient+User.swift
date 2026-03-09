//
//  TwentyFourSixClient+User.swift
//  AmpFin
//
//  Authentication and user methods for 24six API.
//

import Foundation

public extension TwentyFourSixClient {
    /// Fetch available profiles for the given credentials.
    func fetchProfiles(email: String, password: String) async throws -> [(id: String, name: String, pinRequired: Bool)] {
        let response = try await request(ClientRequest<ProfileListResponse>(
            path: "profile-list",
            method: "POST",
            body: [
                "email": email,
                "password": password,
            ]))

        return response.profiles.map { (id: $0.id.value, name: $0.name, pinRequired: $0.pin_required ?? false) }
    }

    /// Login with email, password, profile, and optional PIN.
    func login(email: String, password: String, profileId: String, pin: String? = nil) async throws -> String {
        var payload: [String: Any] = [
            "email": email,
            "password": password,
            "profile_id": profileId,
        ]

        if let pin, !pin.isEmpty {
            payload["pin"] = pin
        }

        let response = try await request(ClientRequest<LoginResponse>(
            path: "login",
            method: "POST",
            body: payload))

        if let serverDeviceId = response.device_id {
            store(deviceId: serverDeviceId)
        }

        return response.token
    }

    /// Register the device with the server.
    func registerDevice() async throws {
        let _ = try await request(ClientRequest<EmptyResponse>(
            path: "device",
            method: "POST",
            body: [
                "device_name": "AmpFin",
                "device_id": deviceId,
            ]))
    }
}
