import Foundation

// OVJECT 앱 소개 카드의 순수 로직(피드 모델·로케일·항목 선택). UIKit·SwiftUI에 의존하지 않는다.
// 이 파일은 OVJECT/feed 저장소 clients/swift/ 에도 같은 내용으로 있고, 거기 test-vectors.json으로 검증한다.
// 고치면 두 곳을 같이 고친다(공용 모듈 대신 복사해서 쓰는 방식, 매뉴얼 참고).

// MARK: - Feed model

struct OvjectHouseFeed: Decodable {
    let schemaVersion: Int
    let app: String
    let locale: String
    let ttlHours: Int?
    let items: [OvjectHouseItem]
}

struct OvjectHouseItem: Decodable, Identifiable, Equatable {
    struct CTA: Decodable, Equatable {
        let label: String
        let action: String
        let url: String?
    }

    let id: String
    let priority: Int?
    let startsAt: String?
    let endsAt: String?
    let platforms: [String]?
    let minAppVersion: String?
    let maxImpressionsPerUser: Int?
    let title: String
    let body: String
    let cta: CTA
    let tags: [String]?
}

// MARK: - Selection (pure, testable)

enum OvjectHouseAdSelection {
    static let hostApp = "kairo"
    static let platform = "ios"
    static let defaultMaxImpressions = 3
    static let allowedHosts: Set<String> = ["apps.apple.com", "ovject.com", "www.ovject.com", "www.threads.com", "threads.com"]

    /// 피드 로케일: 기기 언어를 앱이 지원하는 10개 로케일 중 하나로 맞춘다. 모르면 en.
    static func feedLocale(preferredLanguages: [String] = Locale.preferredLanguages) -> String {
        let first = (preferredLanguages.first ?? "en").replacingOccurrences(of: "_", with: "-")
        let lower = first.lowercased()
        if lower.hasPrefix("zh") {
            let traditional = lower.contains("hant") || lower.hasSuffix("-tw") || lower.hasSuffix("-hk") || lower.hasSuffix("-mo")
            return traditional ? "zh-Hant" : "zh-Hans"
        }
        let base = lower.split(separator: "-").first.map(String.init) ?? "en"
        let supported: Set<String> = ["en", "ko", "ja", "es", "fr", "de", "th", "vi"]
        return supported.contains(base) ? base : "en"
    }

    static func isNewerOrEqual(_ version: String, than minimum: String) -> Bool {
        let a = version.split(separator: ".").map { Int($0) ?? 0 }
        let b = minimum.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(a.count, b.count) {
            let x = i < a.count ? a[i] : 0
            let y = i < b.count ? b[i] : 0
            if x != y { return x > y }
        }
        return true
    }

    static func isSafeURL(_ raw: String?) -> Bool {
        guard let raw, let url = URL(string: raw), url.scheme == "https", let host = url.host else { return false }
        return allowedHosts.contains(host.lowercased())
    }

    /// 지금 보여 줄 수 있는 항목 중 노출이 가장 적은 것, 같으면 priority가 높은 것.
    static func pick(
        from items: [OvjectHouseItem],
        now: Date = Date(),
        appVersion: String,
        impressions: [String: Int]
    ) -> OvjectHouseItem? {
        let formatter = ISO8601DateFormatter()
        let eligible = items.filter { item in
            if item.id.hasPrefix("\(hostApp)-") || (item.tags ?? []).contains(hostApp) { return false }
            if let platforms = item.platforms, !platforms.contains(platform) { return false }
            if let minimum = item.minAppVersion, !isNewerOrEqual(appVersion, than: minimum) { return false }
            if let start = item.startsAt.flatMap(formatter.date(from:)), now < start { return false }
            if let end = item.endsAt.flatMap(formatter.date(from:)), now >= end { return false }
            if item.cta.action != "url" || !isSafeURL(item.cta.url) { return false }
            let limit = item.maxImpressionsPerUser ?? defaultMaxImpressions
            return (impressions[item.id] ?? 0) < limit
        }
        return eligible.min { lhs, rhs in
            let l = impressions[lhs.id] ?? 0
            let r = impressions[rhs.id] ?? 0
            if l != r { return l < r }
            return (lhs.priority ?? 0) > (rhs.priority ?? 0)
        }
    }
}
