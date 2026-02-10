//
//  TwentyFourSixClient+Utility.swift
//  AmpFin
//
//  Utility types for the 24six client.
//

import Foundation

internal extension TwentyFourSixClient {
    struct ClientRequest<T> {
        var path: String
        var method: String
        var body: Any?
        var query: [URLQueryItem]?

        public init(path: String, method: String, body: Any? = nil, query: [URLQueryItem]? = nil) {
            self.path = path
            self.method = method
            self.body = body
            self.query = query
        }
    }

    struct EmptyResponse: Decodable {}
}

public extension TwentyFourSixClient {
    enum ClientError: Error {
        case parseFailed
        case unknownMessage

        case invalidServerUrl
        case invalidHttpBody
        case invalidResponse
    }
}
