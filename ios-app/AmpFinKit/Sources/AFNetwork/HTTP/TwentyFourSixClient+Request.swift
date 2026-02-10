//
//  TwentyFourSixClient+Request.swift
//  AmpFin
//
//  Core HTTP request handler for the 24six API.
//

import Foundation

internal extension TwentyFourSixClient {
    func request<T: Decodable>(_ clientRequest: ClientRequest<T>) async throws -> T {
        var url = Self.baseURL.appending(path: clientRequest.path)

        if let queryItems = clientRequest.query, !queryItems.isEmpty {
            url = url.appending(queryItems: queryItems)
        }

        var request = URLRequest(url: url)
        request.httpMethod = clientRequest.method
        request.httpShouldHandleCookies = true
        request.timeoutInterval = 15

        // Standard 24six headers
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(Self.platformKey, forHTTPHeaderField: "X-Platform-Key")
        request.setValue(Self.apiMinorVersion, forHTTPHeaderField: "X-API-MINOR-VERSION")
        request.setValue(Self.appVersion, forHTTPHeaderField: "app-version")
        request.setValue("iOS", forHTTPHeaderField: "os")
        request.setValue(Self.osVersion, forHTTPHeaderField: "os-version")
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue(deviceId, forHTTPHeaderField: "X-DEVICE-ID")
        request.setValue(deviceSerial, forHTTPHeaderField: "X-DEVICE-SERIAL")

        if let token = _token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body = clientRequest.body {
            if request.value(forHTTPHeaderField: "Content-Type") == nil {
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            }

            do {
                request.httpBody = try JSONSerialization.data(withJSONObject: body)
            } catch {
                logger.fault("Unable to encode body: \(error.localizedDescription)")
                throw ClientError.invalidHttpBody
            }
        }

        do {
            let (data, response) = try await URLSession.shared.data(for: request)

            if !online {
                online = true
            }

            // Handle 401 by re-authenticating
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 401 {
                logger.info("Token expired, attempting re-authentication")
                try await reAuthenticate()
                // Retry the request once
                return try await self.request(clientRequest)
            }

            if T.self == EmptyResponse.self {
                return EmptyResponse() as! T
            }

            return try JSONDecoder().decode(T.self, from: data)
        } catch let error as ClientError {
            throw error
        } catch {
            if let error = error as? URLError {
                let errorCode = error.code

                if errorCode == .appTransportSecurityRequiresSecureConnection ||
                    errorCode == .callIsActive ||
                    errorCode == .cannotConnectToHost ||
                    errorCode == .cannotFindHost ||
                    errorCode == .cannotLoadFromNetwork ||
                    errorCode == .clientCertificateRejected ||
                    errorCode == .clientCertificateRequired ||
                    errorCode == .dataNotAllowed ||
                    errorCode == .dnsLookupFailed ||
                    errorCode == .internationalRoamingOff ||
                    errorCode == .serverCertificateUntrusted ||
                    errorCode == .serverCertificateHasBadDate ||
                    errorCode == .serverCertificateNotYetValid ||
                    errorCode == .serverCertificateHasUnknownRoot ||
                    errorCode == .secureConnectionFailed ||
                    errorCode == .timedOut {
                    logger.fault("Server appears to be unreachable while requesting resource \(url): \(error.errorCode) \(error.localizedDescription)")
                    online = false
                } else {
                    logger.fault("Error while requesting resource \(url): \(error.errorCode) \(error.localizedDescription)")
                }
            } else if let error = error as? DecodingError {
                logger.fault("Error while decoding response \(url)")
                print(error)
            } else {
                logger.fault("Unexpected error while requesting resource \(url): \(error.localizedDescription)")
            }

            throw ClientError.invalidResponse
        }
    }

    /// Perform a raw request that follows redirects manually (for stream URLs).
    func requestStreamURL(path: String, queryItems: [URLQueryItem] = []) async throws -> URL {
        var url = Self.baseURL.appending(path: path)

        if !queryItems.isEmpty {
            url = url.appending(queryItems: queryItems)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 15

        // Standard headers
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(Self.platformKey, forHTTPHeaderField: "X-Platform-Key")
        request.setValue(Self.apiMinorVersion, forHTTPHeaderField: "X-API-MINOR-VERSION")
        request.setValue(Self.appVersion, forHTTPHeaderField: "app-version")
        request.setValue("iOS", forHTTPHeaderField: "os")
        request.setValue(Self.osVersion, forHTTPHeaderField: "os-version")
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue(deviceId, forHTTPHeaderField: "X-DEVICE-ID")
        request.setValue(deviceSerial, forHTTPHeaderField: "X-DEVICE-SERIAL")

        if let token = _token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        // Use a session that doesn't follow redirects
        let config = URLSessionConfiguration.default
        let delegate = NoRedirectDelegate()
        let session = URLSession(configuration: config, delegate: delegate, delegateQueue: nil)

        let (_, response) = try await session.data(for: request)

        if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 302 {
            if let locationString = httpResponse.value(forHTTPHeaderField: "Location"),
               let redirectURL = URL(string: locationString) {
                return redirectURL
            }
        }

        throw ClientError.invalidResponse
    }

    /// Re-authenticate using stored credentials.
    func reAuthenticate() async throws {
        guard let email = _email, let password = _password, let profileId = _profileId else {
            throw ClientError.invalidResponse
        }

        var payload: [String: Any] = [
            "email": email,
            "password": password,
            "profile_id": profileId,
        ]

        if let pin = _profilePin, !pin.isEmpty {
            payload["pin"] = pin
        }

        let loginResponse = try await request(ClientRequest<LoginResponse>(
            path: "login",
            method: "POST",
            body: payload))

        store(token: loginResponse.token)
        if let newDeviceId = loginResponse.device_id {
            store(deviceId: newDeviceId)
        }
    }
}

// MARK: - No-redirect delegate

private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
