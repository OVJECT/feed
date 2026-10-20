extends RefCounted
# OVJECT 앱 소개 카드의 순수 로직(로케일·URL 안전·버전 비교·CTA 해석·항목 선택). 노드·네트워크에 의존하지 않는다.
# 이 파일은 OVJECT/feed 저장소 clients/gdscript/ 에도 같은 내용으로 있고, 거기 test-vectors.json으로 검증한다
# (clients/gdscript/vectors_test.gd). 고치면 두 곳을 같이 고친다(공용 모듈 대신 복사해서 쓰는 방식, 매뉴얼 참고).
# 규칙의 기준은 clients/reference.py 이다.

const FEED_LOCALES: Array[String] = ["en", "ko", "ja", "zh-Hans", "zh-Hant", "es", "fr", "de", "th", "vi"]
const BASE_LOCALES: Array[String] = ["en", "ko", "ja", "es", "fr", "de", "th", "vi"]
const DEFAULT_MAX_IMPRESSIONS := 3
# 피드의 스토어 문구는 App Store를 가리키므로, Google Play 링크는 브랜드 이름으로 표시한다(번역하지 않음).
const PLAY_LABEL := "Google Play"


## 피드 로케일: 기기 언어를 10개 중 하나로 맞춘다. 모르면 en.
static func feed_locale(preferred_languages: Array) -> String:
	var first := "en"
	if not preferred_languages.is_empty():
		first = str(preferred_languages[0])
	var lower := first.replace("_", "-").to_lower()
	if lower.begins_with("zh"):
		var traditional := (
			lower.contains("hant")
			or lower.ends_with("-tw")
			or lower.ends_with("-hk")
			or lower.ends_with("-mo")
		)
		return "zh-Hant" if traditional else "zh-Hans"
	var base := lower.split("-")[0]
	if base == "":
		base = "en"
	return base if BASE_LOCALES.has(base) else "en"


## version >= minimum, 점으로 나눈 숫자를 앞에서부터 비교한다(없는 자리는 0).
static func version_at_least(version: String, minimum: String) -> bool:
	var a := version.split(".")
	var b := minimum.split(".")
	for i in range(maxi(a.size(), b.size())):
		var x := _part(a, i)
		var y := _part(b, i)
		if x != y:
			return x > y
	return true


## https 이고 호스트(대소문자 무시)가 허용 목록과 정확히 같을 때만 true.
static func is_safe_url(raw: Variant, allowed_hosts: Array) -> bool:
	if typeof(raw) != TYPE_STRING:
		return false
	var host := _https_host(raw)
	return host != "" and allowed_hosts.has(host)


## 이 플랫폼에서 항목이 주는 버튼: {"label", "url"}. 쓸 수 있는 링크가 없으면 빈 Dictionary.
## action "url"은 피드의 문구와 주소 그대로. action "store"(iOS·Android 둘 다 쓰는 앱의 피드)는 item.store 의 ID로
## 실행 중인 플랫폼의 스토어 주소를 만든다(ios/macos → App Store, android → Google Play, 문구는 "Google Play").
static func resolve_cta(item: Dictionary, platform: String, host_app: String) -> Dictionary:
	var cta: Dictionary = item.get("cta", {})
	var action := str(cta.get("action", ""))
	if action == "url":
		return {"label": str(cta.get("label", "")), "url": cta.get("url")}
	if action != "store":
		return { }
	var store: Variant = item.get("store")
	if typeof(store) != TYPE_DICTIONARY:
		return { }
	var utm := "utm_source=%s&utm_medium=feedcard&utm_campaign=feedcard&utm_content=%s" % [host_app, item["id"]]
	if platform == "ios" or platform == "macos":
		var app_id := str(store.get("ios_app_id", ""))
		if app_id.is_valid_int() and not app_id.begins_with("-") and not app_id.begins_with("+"):
			return {
				"label": str(cta.get("label", "")),
				"url": "https://apps.apple.com/app/id%s?%s" % [app_id, utm],
			}
	elif platform == "android":
		var package_name := str(store.get("android_package", ""))
		if _is_package_name(package_name):
			return {
				"label": PLAY_LABEL,
				"url": "https://play.google.com/store/apps/details?id=%s&%s" % [package_name, utm],
			}
	return { }


## 지금 보여 줄 항목 하나(없으면 빈 Dictionary).
## 자격: 자기 앱 아님(id 가 "<host>-"로 시작하거나 tags 에 host), platforms 에 내 플랫폼(없으면 모두),
## min_app_version <= 앱 버전, starts_at <= now < ends_at, CTA 가 안전한 주소로 해석됨, 이 기기 노출 횟수 < 한도(기본 3).
## 고르는 법: 노출이 가장 적은 항목 → priority 가 높은 것 → 목록에서 앞선 것.
## now 는 ISO 8601 문자열 또는 유닉스 초.
static func pick(
	items: Array,
	now: Variant,
	app_version: String,
	impressions: Dictionary,
	host_app: String,
	platform: String,
	allowed_hosts: Array,
) -> Dictionary:
	var now_unix := _to_unix(now)
	var best: Dictionary = { }
	var best_shown := 0
	var best_priority := 0
	for item: Dictionary in items:
		var item_id := str(item.get("id", ""))
		if item_id.begins_with(host_app + "-"):
			continue
		var tags: Variant = item.get("tags")
		if typeof(tags) == TYPE_ARRAY and tags.has(host_app):
			continue
		var platforms: Variant = item.get("platforms")
		if typeof(platforms) == TYPE_ARRAY and not platforms.has(platform):
			continue
		var min_version: Variant = item.get("min_app_version")
		if typeof(min_version) == TYPE_STRING and min_version != "" and not version_at_least(app_version, min_version):
			continue
		var starts_at: Variant = item.get("starts_at")
		if typeof(starts_at) == TYPE_STRING and starts_at != "" and now_unix < _to_unix(starts_at):
			continue
		var ends_at: Variant = item.get("ends_at")
		if typeof(ends_at) == TYPE_STRING and ends_at != "" and now_unix >= _to_unix(ends_at):
			continue
		var resolved := resolve_cta(item, platform, host_app)
		if resolved.is_empty() or not is_safe_url(resolved["url"], allowed_hosts):
			continue
		var limit_value: Variant = item.get("max_impressions_per_user")
		var limit := int(limit_value) if limit_value != null else DEFAULT_MAX_IMPRESSIONS
		var shown := int(impressions.get(item_id, 0))
		if shown >= limit:
			continue
		var priority := int(item.get("priority", 0) if item.get("priority") != null else 0)
		if best.is_empty() or shown < best_shown or (shown == best_shown and priority > best_priority):
			best = item
			best_shown = shown
			best_priority = priority
	return best


static func _part(parts: PackedStringArray, index: int) -> int:
	if index >= parts.size():
		return 0
	var part := parts[index]
	return int(part) if part.is_valid_int() and not part.begins_with("-") and not part.begins_with("+") else 0


static func _to_unix(value: Variant) -> int:
	if typeof(value) == TYPE_STRING:
		return int(Time.get_unix_time_from_datetime_string(str(value).trim_suffix("Z")))
	return int(value)


## "https://" 주소의 호스트(소문자). https 가 아니거나 호스트가 비면 "".
static func _https_host(raw: String) -> String:
	var lower := raw.strip_edges().to_lower()
	if not lower.begins_with("https://"):
		return ""
	var rest := lower.substr(8)
	var end := rest.length()
	for stop in ["/", "?", "#"]:
		var at := rest.find(stop)
		if at != -1 and at < end:
			end = at
	var authority := rest.substr(0, end)
	var at_sign := authority.rfind("@")
	if at_sign != -1:
		authority = authority.substr(at_sign + 1)
	if authority.begins_with("["):
		return ""
	var colon := authority.find(":")
	if colon != -1:
		var port := authority.substr(colon + 1)
		authority = authority.substr(0, colon)
		if port != "" and not port.is_valid_int():
			return ""
	return authority


static func _is_package_name(value: String) -> bool:
	var parts := value.split(".")
	if parts.size() < 2:
		return false
	for index in range(parts.size()):
		var part := parts[index]
		if part == "":
			return false
		if index == 0 and not _is_letter(part[0]):
			return false
		for ch in part:
			if not (_is_letter(ch) or ch == "_" or (ch >= "0" and ch <= "9")):
				return false
	return true


static func _is_letter(ch: String) -> bool:
	return (ch >= "a" and ch <= "z") or (ch >= "A" and ch <= "Z")
