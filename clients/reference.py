"""Reference implementation of the house-ad client rules (selection, locale, URL safety, versions).

This is the readable specification in code. A port (Swift, Kotlin, Dart, ...) must give the same answers as
`test-vectors.json`; tools/test_clients.py runs this file and the Swift core against those vectors.
Standard library only."""

from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlsplit

FEED_LOCALES = ("en", "ko", "ja", "zh-Hans", "zh-Hant", "es", "fr", "de", "th", "vi")
_BASE_LOCALES = {"en", "ko", "ja", "es", "fr", "de", "th", "vi"}
DEFAULT_MAX_IMPRESSIONS = 3
PLAY_LABEL = "Google Play"  # the feed's store label names the App Store, so a Google Play link is labelled by brand
_ANDROID_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


def feed_locale(preferred_languages):
    """The feed file to request: the device/app language mapped to one of the ten feed locales, else en."""
    first = (preferred_languages[0] if preferred_languages else "en").replace("_", "-")
    lower = first.lower()
    if lower.startswith("zh"):
        traditional = "hant" in lower or lower.endswith(("-tw", "-hk", "-mo"))
        return "zh-Hant" if traditional else "zh-Hans"
    base = lower.split("-")[0] or "en"
    return base if base in _BASE_LOCALES else "en"


def version_at_least(version, minimum):
    """True when version >= minimum, compared part by part as numbers (missing parts count as 0)."""
    a = [int(part) if part.isdigit() else 0 for part in version.split(".")]
    b = [int(part) if part.isdigit() else 0 for part in minimum.split(".")]
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else 0
        y = b[i] if i < len(b) else 0
        if x != y:
            return x > y
    return True


def is_safe_url(raw, allowed_hosts):
    """https only, and the host (case-insensitive) must be exactly one of the allowed hosts."""
    if not raw:
        return False
    parts = urlsplit(raw)
    return parts.scheme == "https" and bool(parts.hostname) and parts.hostname.lower() in set(allowed_hosts)


def resolve_cta(item, platform, host_app):
    """The button an item gives on this platform: {"label", "url"}, or None when it has no usable link.

    action "url": the feed's label and url as they are. action "store" (a feed made for an app on both stores):
    the store link of the running platform built from item["store"] (iOS/macOS -> App Store ios_app_id,
    android -> Google Play android_package, labelled "Google Play"). utm_source is the host app, the campaign is
    "feedcard", utm_content the item id. A missing or malformed store id gives None."""
    cta = item["cta"]
    action = cta.get("action")
    if action == "url":
        return {"label": cta.get("label", ""), "url": cta.get("url")}
    if action != "store":
        return None
    store = item.get("store") or {}
    utm = f"utm_source={host_app}&utm_medium=feedcard&utm_campaign=feedcard&utm_content={item['id']}"
    if platform in ("ios", "macos"):
        app_id = str(store.get("ios_app_id") or "")
        if app_id.isdigit():
            return {"label": cta.get("label", ""), "url": f"https://apps.apple.com/app/id{app_id}?{utm}"}
    elif platform == "android":
        package = str(store.get("android_package") or "")
        if _ANDROID_PACKAGE.match(package):
            return {"label": PLAY_LABEL, "url": f"https://play.google.com/store/apps/details?id={package}&{utm}"}
    return None


def _parse(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def pick(items, *, now, app_version, impressions, host_app, platform, allowed_hosts):
    """The one item to show now, or None.

    Eligible when: not about the host app (id starts with "<host>-" or tags contain host), shown on this
    platform (platforms missing = any), app version >= min_app_version, starts_at <= now < ends_at,
    CTA resolves (resolve_cta: action "url", or "store" with this platform's store id) to a safe URL, and this device has shown it fewer times than
    max_impressions_per_user (default 3). Among eligible items: fewest impressions first, then higher
    priority, then the earlier one in the list."""
    now = _parse(now)
    eligible = []
    for item in items:
        if item["id"].startswith(f"{host_app}-") or host_app in (item.get("tags") or []):
            continue
        if item.get("platforms") is not None and platform not in item["platforms"]:
            continue
        if item.get("min_app_version") and not version_at_least(app_version, item["min_app_version"]):
            continue
        if item.get("starts_at") and now < _parse(item["starts_at"]):
            continue
        if item.get("ends_at") and now >= _parse(item["ends_at"]):
            continue
        resolved = resolve_cta(item, platform, host_app)
        if resolved is None or not is_safe_url(resolved["url"], allowed_hosts):
            continue
        limit = item.get("max_impressions_per_user")
        if (impressions.get(item["id"], 0)) >= (limit if limit is not None else DEFAULT_MAX_IMPRESSIONS):
            continue
        eligible.append(item)
    if not eligible:
        return None
    best = min(
        enumerate(eligible),
        key=lambda pair: (impressions.get(pair[1]["id"], 0), -(pair[1].get("priority") or 0), pair[0]),
    )
    return best[1]
