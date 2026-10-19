// clients/test-vectors.json을 Swift 코어(OvjectHouseAdCore.swift)로 검증하는 실행기.
// 실행: swiftc OvjectHouseAdCore.swift main.swift -o /tmp/ovject-vectors && /tmp/ovject-vectors ../test-vectors.json
import Foundation

struct Vectors: Decodable {
    struct LocaleCase: Decodable { let preferred: [String]; let expected: String }
    struct URLCase: Decodable { let url: String?; let expected: Bool }
    struct SemverCase: Decodable { let version: String; let minimum: String; let expected: Bool }
    struct PickCase: Decodable {
        let name: String
        let hostApp: String
        let platform: String
        let appVersion: String
        let now: String
        let impressions: [String: Int]
        let items: [OvjectHouseItem]
        let expectedId: String?
    }
    let locale: [LocaleCase]
    let urlSafety: [URLCase]
    let semver: [SemverCase]
    let pick: [PickCase]
}

guard CommandLine.arguments.count == 2,
      let data = FileManager.default.contents(atPath: CommandLine.arguments[1]) else {
    print("usage: ovject-vectors <test-vectors.json>")
    exit(2)
}
let decoder = JSONDecoder()
decoder.keyDecodingStrategy = .convertFromSnakeCase
let vectors = try decoder.decode(Vectors.self, from: data)

var failures = 0
func check(_ ok: Bool, _ label: String) {
    if !ok { failures += 1; print("FAIL \(label)") }
}

for c in vectors.locale {
    let got = OvjectHouseAdSelection.feedLocale(preferredLanguages: c.preferred)
    check(got == c.expected, "locale \(c.preferred) -> \(got), expected \(c.expected)")
}
for c in vectors.urlSafety {
    let got = OvjectHouseAdSelection.isSafeURL(c.url)
    check(got == c.expected, "url \(c.url ?? "nil") -> \(got), expected \(c.expected)")
}
for c in vectors.semver {
    let got = OvjectHouseAdSelection.isNewerOrEqual(c.version, than: c.minimum)
    check(got == c.expected, "semver \(c.version) >= \(c.minimum) -> \(got), expected \(c.expected)")
}
let iso = ISO8601DateFormatter()
for c in vectors.pick {
    // 이 Swift 코어의 호스트 앱·플랫폼은 상수(kairo, ios)라서 그 조건의 케이스만 비교한다.
    guard c.hostApp == OvjectHouseAdSelection.hostApp, c.platform == OvjectHouseAdSelection.platform else { continue }
    let picked = OvjectHouseAdSelection.pick(
        from: c.items, now: iso.date(from: c.now)!, appVersion: c.appVersion, impressions: c.impressions
    )
    check(picked?.id == c.expectedId, "pick '\(c.name)' -> \(picked?.id ?? "nil"), expected \(c.expectedId ?? "nil")")
}

let total = vectors.locale.count + vectors.urlSafety.count + vectors.semver.count + vectors.pick.count
print(failures == 0 ? "OK \(total) cases" : "\(failures) failures of \(total) cases")
exit(failures == 0 ? 0 : 1)
