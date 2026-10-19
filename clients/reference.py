"""Reference implementation of the house-ad client rules (selection, locale, URL safety, versions).

This is the readable specification in code. A port (Swift, Kotlin, Dart, ...) must give the same answers as
`test-vectors.json`; tools/test_clients.py runs this file and the Swift core against those vectors.
Standard library only."""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlsplit

FEED_LOCALES = ("en", "ko", "ja", "zh-Hans", "zh-Hant", "es", "fr", "de", "th", "vi")
_BASE_LOCALES = {"en", "ko", "ja", "es", "fr", "de", "th", "vi"}
DEFAULT_MAX_IMPRESSIONS = 3


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


def _parse(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def pick(items, *, now, app_version, impressions, host_app, platform, allowed_hosts):
    """The one item to show now, or None.

    Eligible when: not about the host app (id starts with "<host>-" or tags contain host), shown on this
    platform (platforms missing = any), app version >= min_app_version, starts_at <= now < ends_at,
    CTA is action "url" with a safe URL, and this device has shown it fewer times than
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
        cta = item["cta"]
        if cta.get("action") != "url" or not is_safe_url(cta.get("url"), allowed_hosts):
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
