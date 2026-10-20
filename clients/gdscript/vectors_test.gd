extends SceneTree
# clients/test-vectors.json 을 GDScript 코어(ovject_house_ad_core.gd)로 검증하는 실행기.
# 실행: godot --headless --script clients/gdscript/vectors_test.gd -- clients/test-vectors.json

const Core = preload("ovject_house_ad_core.gd")


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		print("usage: godot --headless --script vectors_test.gd -- <test-vectors.json>")
		quit(2)
		return
	var vectors: Variant = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	if typeof(vectors) != TYPE_DICTIONARY:
		print("cannot read %s" % args[0])
		quit(2)
		return

	var failures := 0
	var total := 0
	var reference_hosts: Array = vectors["reference_allowed_hosts"]

	for c: Dictionary in vectors["locale"]:
		total += 1
		var got := Core.feed_locale(c["preferred"])
		if got != c["expected"]:
			failures += 1
			print("FAIL locale %s -> %s, expected %s" % [c["preferred"], got, c["expected"]])
	for c: Dictionary in vectors["url_safety"]:
		total += 1
		var got := Core.is_safe_url(c["url"], reference_hosts)
		if got != c["expected"]:
			failures += 1
			print("FAIL url %s -> %s, expected %s" % [c["url"], got, c["expected"]])
	for c: Dictionary in vectors["semver"]:
		total += 1
		var got := Core.version_at_least(c["version"], c["minimum"])
		if got != c["expected"]:
			failures += 1
			print("FAIL semver %s >= %s -> %s, expected %s" % [c["version"], c["minimum"], got, c["expected"]])
	for c: Dictionary in vectors["cta"]:
		total += 1
		var got := Core.resolve_cta(c["item"], c["platform"], c["host_app"])
		var expected: Variant = c["expected"]
		var same: bool = got.is_empty() if expected == null else (got == expected)
		if not same:
			failures += 1
			print("FAIL cta '%s' -> %s, expected %s" % [c["name"], got, expected])
	for c: Dictionary in vectors["pick"]:
		total += 1
		var hosts: Array = c.get("allowed_hosts", reference_hosts)
		var impressions: Dictionary = c["impressions"]
		var picked := Core.pick(
			c["items"], c["now"], c["app_version"], impressions, c["host_app"], c["platform"], hosts
		)
		var picked_id: Variant = picked["id"] if not picked.is_empty() else null
		if picked_id != c["expected_id"]:
			failures += 1
			print("FAIL pick '%s' -> %s, expected %s" % [c["name"], picked_id, c["expected_id"]])

	print("OK %d cases" % total if failures == 0 else "%d failures of %d cases" % [failures, total])
	quit(0 if failures == 0 else 1)
