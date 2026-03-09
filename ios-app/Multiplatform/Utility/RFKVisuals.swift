//
//  RFKVisuals.swift
//  Multiplatform
//
//  Local replacement for the removed RFKVisuals package.
//  Provides dominant color extraction from images.
//

import SwiftUI
import CoreImage

enum RFKVisuals {
    struct DominantColor {
        let color: Color
        let frequency: Double
    }

    static func extractDominantColors(_ count: Int, image: UIImage) async throws -> [DominantColor] {
        guard let cgImage = image.cgImage else { return [] }

        let width = min(cgImage.width, 100)
        let height = min(cgImage.height, 100)

        guard let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return [] }

        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

        guard let data = context.data else { return [] }

        let pointer = data.bindMemory(to: UInt8.self, capacity: width * height * 4)
        var buckets = [Int: (r: Double, g: Double, b: Double, count: Int)]()
        let bucketSize = 32

        for y in stride(from: 0, to: height, by: 2) {
            for x in stride(from: 0, to: width, by: 2) {
                let offset = (y * width + x) * 4
                let r = Int(pointer[offset])
                let g = Int(pointer[offset + 1])
                let b = Int(pointer[offset + 2])

                let key = (r / bucketSize) * 1000000 + (g / bucketSize) * 1000 + (b / bucketSize)

                if var bucket = buckets[key] {
                    bucket.r += Double(r)
                    bucket.g += Double(g)
                    bucket.b += Double(b)
                    bucket.count += 1
                    buckets[key] = bucket
                } else {
                    buckets[key] = (Double(r), Double(g), Double(b), 1)
                }
            }
        }

        let totalPixels = Double(buckets.values.reduce(0) { $0 + $1.count })
        let sorted = buckets.values.sorted { $0.count > $1.count }
        let top = sorted.prefix(count)

        return top.map { bucket in
            let r = bucket.r / Double(bucket.count) / 255.0
            let g = bucket.g / Double(bucket.count) / 255.0
            let b = bucket.b / Double(bucket.count) / 255.0
            return DominantColor(
                color: Color(red: r, green: g, blue: b),
                frequency: Double(bucket.count) / totalPixels
            )
        }
    }

    static func brightnessExtremeFilter(_ colors: [Color], threshold: Double = 0.1) -> [Color] {
        colors.filter { color in
            let components = UIColor(color).hsba
            return components.brightness > threshold && components.brightness < (1.0 - threshold)
        }
    }

    static func determineMostSaturated(_ colors: [Color]) -> Color? {
        colors.max { a, b in
            UIColor(a).hsba.saturation < UIColor(b).hsba.saturation
        }
    }
}

private extension UIColor {
    struct HSBA {
        let hue: CGFloat
        let saturation: CGFloat
        let brightness: CGFloat
        let alpha: CGFloat
    }

    var hsba: HSBA {
        var h: CGFloat = 0
        var s: CGFloat = 0
        var b: CGFloat = 0
        var a: CGFloat = 0
        getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        return HSBA(hue: h, saturation: s, brightness: b, alpha: a)
    }
}
