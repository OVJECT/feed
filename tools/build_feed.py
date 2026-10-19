#!/usr/bin/env python3
"""Build and lint OVJECT in-app news feed files (this repository, OVJECT/feed).

Source   src/<app>/<item-id>.json
         (one file per item: shared fields + per-locale strings + free `notes`)
Output   v1/<app>/<locale>.json for the 10 locales
         (schema tools/feed-schema.json, checked here without `jsonschema`)

Usage (from the repository root; paths default to src/ and v1/)
  tools/build_feed.py                               # every app under src/
  tools/build_feed.py --app oryth                   # one app
  tools/build_feed.py --skip-unchanged              # what CI runs: rewrite only files whose
                                                    # content (apart from generated_at) changed
  tools/build_feed.py --app oryth --check           # build in memory, lint only
  tools/build_feed.py --app oryth --include-pending # local preview of unapproved items
  tools/build_feed.py --check v1/oryth/*.json       # lint existing files (pending items fail)

Standard library only. Exit code 0 when everything passed, 1 otherwise.
This file is the canonical copy; marketing/scripts/build_feed.py is a snapshot
used for drafts and local linting.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO_ROOT / "src"
DEFAULT_OUT = REPO_ROOT / "v1"

LOCALES = ["en", "ko", "ja", "zh-Hans", "zh-Hant", "es", "fr", "de", "th", "vi"]
SOURCE_LOCALE = "en"
KINDS = ("promo", "news", "community", "survey")
PLATFORMS = ("ios", "android", "macos")        # host app platforms on which an item is shown
RUNS_ON = ("macos", "ios", "android", "web", "windows")  # platforms the promoted app itself runs on

# Feed-level `links`: a row of fixed destinations for the app's OVJECT page
# (home page, store, support, privacy, later socials). Source: src/_links/<app>.json.
LINKS_DIR = "_links"
# Derived hosts: an app whose feed is built from another app's items (src/_hosts/<app>.json),
# e.g. KAIRO's gallery card reuses the Oryth items. The parent's approval and gate results carry over.
HOSTS_DIR = "_hosts"
HOST_KEYS = ("derive_from", "platforms", "min_app_version", "max_impressions_per_user", "cta_hosts", "exclude")
MAX_LINKS = 8
LINK_LABEL_MAX = 24
_OVJECT_HOSTS = ("ovject.github.io", "ovject.com")
# kind -> (default English label, allowed hosts; a subdomain of an allowed host also passes)
LINK_KINDS = {
    "website": ("Website", _OVJECT_HOSTS),
    "appstore": ("App Store", ("apps.apple.com",)),
    "support": ("Support", _OVJECT_HOSTS),
    "privacy": ("Privacy", _OVJECT_HOSTS),
    "instagram": ("Instagram", ("instagram.com",)),
    "x": ("X", ("x.com", "twitter.com")),
    "threads": ("Threads", ("threads.net", "threads.com")),
    "youtube": ("YouTube", ("youtube.com", "youtu.be")),
    "discord": ("Discord", ("discord.gg", "discord.com")),
    "bluesky": ("Bluesky", ("bsky.app",)),
    "tiktok": ("TikTok", ("tiktok.com",)),
    "github": ("GitHub", ("github.com",)),
}
ACTIONS = ("url", "store", "dismiss")
SCHEMA_VERSION = 1
MAX_ITEMS = 10
MAX_FILE_BYTES = 20 * 1024
TITLE_MAX = 40
BODY_MAX = 120
LABEL_MAX = 16
ALT_MAX = 120
TTL_MIN, TTL_MAX = 1, 168
DEFAULT_TTL_HOURS = 12
PENDING_GATE = "pending"

ID_RE = re.compile(r"^[a-z0-9-]{3,64}$")
APP_RE = re.compile(r"^[a-z0-9-]{2,32}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
IOS_APP_ID_RE = re.compile(r"^\d+$")
ANDROID_PKG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
TAG_RE = re.compile(r"^[a-z0-9-]{1,32}$")
HTTPS_RE = re.compile(r"^https://")
UTM_RE = re.compile(
    r"^https://[^\s]+utm_source=[^&\s]+.*utm_medium=feedcard.*utm_campaign=[^&\s]+.*utm_content=[^&\s]+"
)

TOP_REQUIRED = ("schema_version", "app", "locale", "generated_at", "ttl_hours", "items")
TOP_ALLOWED = TOP_REQUIRED + ("links", "signature")
ITEM_REQUIRED = (
    "id", "kind", "priority", "starts_at", "ends_at", "platforms",
    "title", "body", "cta", "secondary", "approval",
)
ITEM_ALLOWED = ITEM_REQUIRED + (
    "runs_on", "min_app_version", "max_impressions_per_user", "image", "store", "tags",
)
STRING_KEYS = ("title", "body", "cta_label", "secondary_label")
SOURCE_REQUIRED = (
    "id", "kind", "priority", "starts_at", "ends_at", "platforms",
    "cta", "secondary", "approval", "strings",
)
SOURCE_ALLOWED = SOURCE_REQUIRED + (
    "notes", "review", "gate_context", "runs_on", "min_app_version", "max_impressions_per_user", "image", "store", "tags",
)
# `gate_context` is the evidence handed to the Nimble gate (scripts/gate_feed.py):
#   {"app_summary": "...", "source_excerpts": ["...", ...]}
# It never reaches the output either.
# `review` holds per-locale gate results written by the gate step:
#   {"<locale>": {"gate": "pass" | "fail" | "needs_human", ...free memo...}}
# A locale whose gate is anything but "pass" is left out of that locale's
# file (CROSS_PROMO.md §8-2: no en fallback for failed gates). No review
# entry means the gate has not run yet; the item is still emitted (it is
# pending human approval anyway). `notes` and `review` never reach the output.
GATE_PASS = "pass"
GATE_VALUES = (GATE_PASS, "fail", "needs_human")


class BuildError(Exception):
    """A source or built feed failed validation."""


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------

def parse_datetime(value):
    """Return an aware datetime for an ISO 8601 string, or None if invalid."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_pending(item):
    approval = item.get("approval")
    if not isinstance(approval, dict):
        return True
    return approval.get("gate") == PENDING_GATE or not approval.get("approved_by")


def utm_params(url):
    query = url.split("?", 1)[1] if "?" in url else ""
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = value
    return params


# ----------------------------------------------------------------------------
# validation (mirrors feed-schema.json plus the §8-6 lint rules)
# ----------------------------------------------------------------------------

def _check_keys(obj, required, allowed, path, errors):
    for key in required:
        if key not in obj:
            errors.append(f"{path}: missing required key '{key}'")
    for key in obj:
        if key not in allowed:
            errors.append(f"{path}: unknown key '{key}' (additionalProperties=false)")


def _check_action(obj, path, errors, *, app=None, item_id=None):
    if not isinstance(obj, dict):
        errors.append(f"{path}: must be an object")
        return
    _check_keys(obj, ("label", "action"), ("label", "action", "url"), path, errors)
    label = obj.get("label")
    if not isinstance(label, str) or not (1 <= len(label) <= LABEL_MAX):
        errors.append(f"{path}.label: must be 1..{LABEL_MAX} chars")
    action = obj.get("action")
    if action not in ACTIONS:
        errors.append(f"{path}.action: must be one of {list(ACTIONS)}")
    url = obj.get("url")
    if action == "url":
        if not isinstance(url, str):
            errors.append(f"{path}.url: required when action=url")
        else:
            if not HTTPS_RE.match(url):
                errors.append(f"{path}.url: must start with https://")
            if not UTM_RE.match(url):
                errors.append(
                    f"{path}.url: must carry utm_source, utm_medium=feedcard, utm_campaign, utm_content"
                )
            else:
                params = utm_params(url)
                if app is not None and params.get("utm_source") != app:
                    errors.append(f"{path}.url: utm_source must equal app '{app}'")
                if item_id is not None and params.get("utm_content") != item_id:
                    errors.append(f"{path}.url: utm_content must equal item id '{item_id}'")
    elif url is not None and not isinstance(url, str):
        errors.append(f"{path}.url: must be a string when present")


def _check_runs_on(value, path, errors):
    """`runs_on` (optional): the platforms the promoted app itself runs on."""
    if not isinstance(value, list) or not value:
        errors.append(f"{path}: must be a non-empty array of {list(RUNS_ON)}")
        return
    if len(set(map(str, value))) != len(value):
        errors.append(f"{path}: must be unique")
    for entry in value:
        if entry not in RUNS_ON:
            errors.append(f"{path}: unknown platform '{entry}' (allowed: {list(RUNS_ON)})")


def _check_image(obj, path, errors):
    if not isinstance(obj, dict):
        errors.append(f"{path}: must be an object")
        return
    _check_keys(obj, ("url", "width", "height", "alt"), ("url", "width", "height", "alt"), path, errors)
    url = obj.get("url")
    if not isinstance(url, str) or not HTTPS_RE.match(url):
        errors.append(f"{path}.url: must start with https://")
    for key in ("width", "height"):
        if not is_int(obj.get(key)) or obj.get(key) < 1:
            errors.append(f"{path}.{key}: must be an integer >= 1")
    alt = obj.get("alt")
    if not isinstance(alt, str) or not (1 <= len(alt) <= ALT_MAX):
        errors.append(f"{path}.alt: must be 1..{ALT_MAX} chars")


def _check_store(obj, path, errors):
    if obj is None:
        return
    if not isinstance(obj, dict):
        errors.append(f"{path}: must be an object or null")
        return
    _check_keys(obj, (), ("ios_app_id", "android_package"), path, errors)
    ios_app_id = obj.get("ios_app_id")
    if ios_app_id is not None and (not isinstance(ios_app_id, str) or not IOS_APP_ID_RE.match(ios_app_id)):
        errors.append(f"{path}.ios_app_id: must be a digit string")
    package = obj.get("android_package")
    if package is not None and (not isinstance(package, str) or not ANDROID_PKG_RE.match(package)):
        errors.append(f"{path}.android_package: must look like a.b.c")


def _check_approval(obj, path, errors, *, allow_pending):
    if not isinstance(obj, dict):
        errors.append(f"{path}: must be an object (items without approval are rejected)")
        return
    keys = ("gate", "approved_by", "approved_at")
    _check_keys(obj, keys, keys, path, errors)
    for key in keys:
        if key in obj and not isinstance(obj[key], str):
            errors.append(f"{path}.{key}: must be a string")
    gate = obj.get("gate")
    approved_by = obj.get("approved_by")
    approved_at = obj.get("approved_at")
    pending = gate == PENDING_GATE or not approved_by
    if pending:
        if not allow_pending:
            errors.append(f"{path}: item is pending approval (gate/approved_by); not allowed in this build")
        return
    if not isinstance(gate, str) or not gate:
        errors.append(f"{path}.gate: must be a non-empty string")
    if parse_datetime(approved_at) is None:
        errors.append(f"{path}.approved_at: must be an ISO 8601 date-time")


def _host_allowed(host, allowed):
    return any(host == base or host.endswith("." + base) for base in allowed)


def validate_links(links, path, errors, *, allow_empty=False):
    """Check a `links` array (feed level or the _links source file).

    The item UTM rule does not apply here; links are fixed destinations."""
    if not isinstance(links, list) or (not links and not allow_empty):
        errors.append(f"{path}: must be a non-empty array of at most {MAX_LINKS} links")
        return
    if len(links) > MAX_LINKS:
        errors.append(f"{path}: at most {MAX_LINKS} links (got {len(links)})")
    seen = set()
    for index, link in enumerate(links):
        link_path = f"{path}[{index}]"
        if not isinstance(link, dict):
            errors.append(f"{link_path}: must be an object")
            continue
        _check_keys(link, ("kind", "url"), ("kind", "label", "url"), link_path, errors)
        kind = link.get("kind")
        spec = LINK_KINDS.get(kind) if isinstance(kind, str) else None
        if spec is None:
            errors.append(f"{link_path}.kind: unknown kind {kind!r} (allowed: {list(LINK_KINDS)})")
        if "label" in link:
            label = link["label"]
            if (not isinstance(label, str) or not (1 <= len(label) <= LINK_LABEL_MAX)
                    or not label.isascii() or not label.isprintable()):
                errors.append(f"{link_path}.label: must be 1..{LINK_LABEL_MAX} printable ASCII chars (English); omit it for the default")
        url = link.get("url")
        if not isinstance(url, str) or not HTTPS_RE.match(url) or re.search(r"\s", url):
            errors.append(f"{link_path}.url: must be an https:// URL without spaces")
            continue
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            parts.port  # raises ValueError on a bad port
        except ValueError:
            errors.append(f"{link_path}.url: not a valid URL")
            continue
        if parts.username is not None or parts.password is not None or parts.port is not None:
            errors.append(f"{link_path}.url: user info and ports are not allowed")
        if spec is not None and not _host_allowed(host, spec[1]):
            errors.append(f"{link_path}.url: host '{host}' is not allowed for kind '{kind}' (allowed: {list(spec[1])})")
        if url in seen:
            errors.append(f"{link_path}.url: duplicate url")
        seen.add(url)


def normalize_links(links):
    """Output form: label filled with the kind's English default when omitted."""
    return [
        {"kind": link["kind"], "label": link.get("label") or LINK_KINDS[link["kind"]][0], "url": link["url"]}
        for link in links
    ]


def validate_item(item, index, errors, *, app=None, allow_pending=False):
    path = f"items[{index}]"
    if not isinstance(item, dict):
        errors.append(f"{path}: must be an object")
        return
    _check_keys(item, ITEM_REQUIRED, ITEM_ALLOWED, path, errors)

    item_id = item.get("id")
    if not isinstance(item_id, str) or not ID_RE.match(item_id):
        errors.append(f"{path}.id: must match [a-z0-9-]{{3,64}}")
        item_id = None
    if item.get("kind") not in KINDS:
        errors.append(f"{path}.kind: must be one of {list(KINDS)}")
    if not is_int(item.get("priority")):
        errors.append(f"{path}.priority: must be an integer")

    starts = parse_datetime(item.get("starts_at"))
    ends = parse_datetime(item.get("ends_at"))
    if starts is None:
        errors.append(f"{path}.starts_at: must be an ISO 8601 date-time")
    if ends is None:
        errors.append(f"{path}.ends_at: must be an ISO 8601 date-time")
    if starts is not None and ends is not None and ends <= starts:
        errors.append(f"{path}: ends_at must be after starts_at")

    platforms = item.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        errors.append(f"{path}.platforms: must be a non-empty array")
    else:
        if len(set(map(str, platforms))) != len(platforms):
            errors.append(f"{path}.platforms: must be unique")
        for platform in platforms:
            if platform not in PLATFORMS:
                errors.append(f"{path}.platforms: unknown platform '{platform}'")
    if "runs_on" in item:
        _check_runs_on(item["runs_on"], f"{path}.runs_on", errors)

    version = item.get("min_app_version")
    if version is not None and (not isinstance(version, str) or not SEMVER_RE.match(version)):
        errors.append(f"{path}.min_app_version: must be semver like 1.2.3")
    impressions = item.get("max_impressions_per_user")
    if impressions is not None and (not is_int(impressions) or impressions < 1):
        errors.append(f"{path}.max_impressions_per_user: must be an integer >= 1")

    title = item.get("title")
    if not isinstance(title, str) or not (1 <= len(title) <= TITLE_MAX):
        errors.append(f"{path}.title: must be 1..{TITLE_MAX} chars")
    body = item.get("body")
    if not isinstance(body, str) or not (1 <= len(body) <= BODY_MAX):
        errors.append(f"{path}.body: must be 1..{BODY_MAX} chars")
    for text_key in ("title", "body"):
        text = item.get(text_key)
        if isinstance(text, str) and re.search(r"<[a-zA-Z/!]", text):
            errors.append(f"{path}.{text_key}: HTML/markup is not allowed (data only)")

    if "image" in item and item["image"] is not None:
        _check_image(item["image"], f"{path}.image", errors)

    cta = item.get("cta")
    if "cta" in item:
        _check_action(cta, f"{path}.cta", errors, app=app, item_id=item_id)
    secondary = item.get("secondary")
    if "secondary" in item:
        if not isinstance(secondary, dict):
            errors.append(f"{path}.secondary: must be an object")
        else:
            _check_keys(secondary, ("label", "action"), ("label", "action"), f"{path}.secondary", errors)
            label = secondary.get("label")
            if not isinstance(label, str) or not (1 <= len(label) <= LABEL_MAX):
                errors.append(f"{path}.secondary.label: must be 1..{LABEL_MAX} chars")
            if secondary.get("action") != "dismiss":
                errors.append(f"{path}.secondary.action: must be 'dismiss'")

    if "store" in item:
        _check_store(item["store"], f"{path}.store", errors)
    if isinstance(cta, dict) and cta.get("action") == "store" and not isinstance(item.get("store"), dict):
        errors.append(f"{path}.store: required object when cta.action=store")

    tags = item.get("tags")
    if tags is not None:
        if not isinstance(tags, list):
            errors.append(f"{path}.tags: must be an array")
        else:
            for tag in tags:
                if not isinstance(tag, str) or not TAG_RE.match(tag):
                    errors.append(f"{path}.tags: invalid tag '{tag}'")

    if "approval" in item:
        _check_approval(item["approval"], f"{path}.approval", errors, allow_pending=allow_pending)


def validate_feed(doc, *, expected_app=None, expected_locale=None, allow_pending=False):
    """Return a list of error strings; empty means the feed passes."""
    errors = []
    if not isinstance(doc, dict):
        return ["feed: must be a JSON object"]
    _check_keys(doc, TOP_REQUIRED, TOP_ALLOWED, "feed", errors)

    if doc.get("schema_version") != SCHEMA_VERSION or not is_int(doc.get("schema_version")):
        errors.append(f"feed.schema_version: must be {SCHEMA_VERSION}")
    app = doc.get("app")
    if not isinstance(app, str) or not APP_RE.match(app):
        errors.append("feed.app: must match [a-z0-9-]{2,32}")
        app = None
    elif expected_app is not None and app != expected_app:
        errors.append(f"feed.app: '{app}' does not match path app '{expected_app}'")
    locale = doc.get("locale")
    if locale not in LOCALES:
        errors.append(f"feed.locale: must be one of {LOCALES}")
    elif expected_locale is not None and locale != expected_locale:
        errors.append(f"feed.locale: '{locale}' does not match path locale '{expected_locale}'")
    if parse_datetime(doc.get("generated_at")) is None:
        errors.append("feed.generated_at: must be an ISO 8601 date-time")
    ttl = doc.get("ttl_hours")
    if not is_int(ttl) or not (TTL_MIN <= ttl <= TTL_MAX):
        errors.append(f"feed.ttl_hours: must be an integer {TTL_MIN}..{TTL_MAX}")
    signature = doc.get("signature")
    if signature is not None and not isinstance(signature, str):
        errors.append("feed.signature: must be a string or null")
    if "links" in doc:
        validate_links(doc["links"], "feed.links", errors)

    items = doc.get("items")
    if not isinstance(items, list):
        errors.append("feed.items: must be an array")
    else:
        if len(items) > MAX_ITEMS:
            errors.append(f"feed.items: at most {MAX_ITEMS} items")
        seen = set()
        for index, item in enumerate(items):
            validate_item(item, index, errors, app=app, allow_pending=allow_pending)
            item_id = item.get("id") if isinstance(item, dict) else None
            if item_id in seen:
                errors.append(f"items[{index}].id: duplicate id '{item_id}'")
            seen.add(item_id)

    size = len(serialize(doc).encode("utf-8"))
    if size > MAX_FILE_BYTES:
        errors.append(f"feed: serialized size {size} bytes exceeds {MAX_FILE_BYTES}")
    return errors


def serialize(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


# ----------------------------------------------------------------------------
# sources → locale feeds
# ----------------------------------------------------------------------------

def validate_source(source, path):
    errors = []
    if not isinstance(source, dict):
        return [f"{path}: must be a JSON object"]
    _check_keys(source, SOURCE_REQUIRED, SOURCE_ALLOWED, str(path), errors)
    item_id = source.get("id")
    stem = Path(path).stem
    if item_id != stem:
        errors.append(f"{path}: id '{item_id}' must equal the file name '{stem}'")
    if "runs_on" in source:
        _check_runs_on(source["runs_on"], f"{path}.runs_on", errors)
    strings = source.get("strings")
    if not isinstance(strings, dict):
        errors.append(f"{path}.strings: must be an object keyed by locale")
    else:
        for locale, entry in strings.items():
            if locale not in LOCALES:
                errors.append(f"{path}.strings: unknown locale '{locale}'")
                continue
            if not isinstance(entry, dict):
                errors.append(f"{path}.strings.{locale}: must be an object")
                continue
            for key in entry:
                if key not in STRING_KEYS:
                    errors.append(f"{path}.strings.{locale}: unknown key '{key}'")
            # A locale is either fully written or absent; a half-filled locale
            # is a mistake, not a fallback request.
            if not complete_strings(entry):
                errors.append(
                    f"{path}.strings.{locale}: present but incomplete; fill all of {list(STRING_KEYS)} or remove the locale"
                )
        if not complete_strings(strings.get(SOURCE_LOCALE)):
            errors.append(f"{path}.strings.{SOURCE_LOCALE}: the source locale must have all of {list(STRING_KEYS)}")
    review = source.get("review")
    if review is not None:
        if not isinstance(review, dict):
            errors.append(f"{path}.review: must be an object keyed by locale")
        else:
            for locale, entry in review.items():
                if locale not in LOCALES:
                    errors.append(f"{path}.review: unknown locale '{locale}'")
                elif not isinstance(entry, dict) or entry.get("gate") not in GATE_VALUES:
                    errors.append(f"{path}.review.{locale}: needs 'gate' in {list(GATE_VALUES)}")
    for key in ("cta", "secondary"):
        block = source.get(key)
        if isinstance(block, dict) and "label" in block:
            errors.append(f"{path}.{key}.label: labels live in strings.<locale>, not here")
    return errors


def complete_strings(entry):
    if not isinstance(entry, dict):
        return False
    return all(isinstance(entry.get(key), str) and entry.get(key) for key in STRING_KEYS)


def discover_apps(src_root):
    """App slugs under <src_root>/ (one folder per app), sorted."""
    root = Path(src_root)
    if not root.is_dir():
        raise BuildError(f"source root not found: {root}")
    apps = {entry.name for entry in root.iterdir() if entry.is_dir() and APP_RE.match(entry.name)}
    hosts_dir = root / HOSTS_DIR
    if hosts_dir.is_dir():
        apps.update(path.stem for path in hosts_dir.glob("*.json") if APP_RE.match(path.stem))
    apps = sorted(apps)
    if not apps:
        raise BuildError(f"no app folders under {root}")
    return apps


def self_promotion_errors(source, app, path):
    """An app never introduces itself (JY, 2026-10-19).

    In the feed built for `app`, an item whose `tags` contain `app` or whose
    id starts with "<app>-" is an error, not a silent skip."""
    errors = []
    item_id = source.get("id")
    if isinstance(item_id, str) and item_id.startswith(f"{app}-"):
        errors.append(f"{path}: id '{item_id}' starts with '{app}-' but this is the {app} feed; an app does not introduce itself")
    tags = source.get("tags")
    if isinstance(tags, list) and app in tags:
        errors.append(f"{path}: tags contain '{app}' but this is the {app} feed; an app does not introduce itself")
    return errors


def load_sources(src_root, app):
    app_dir = Path(src_root) / app
    if not app_dir.is_dir():
        if (Path(src_root) / HOSTS_DIR / f"{app}.json").is_file():
            return []  # a derived host may have no items of its own
        raise BuildError(f"source folder not found: {app_dir}")
    sources = []
    errors = []
    for path in sorted(app_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                source = json.load(handle)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: cannot read JSON ({exc})")
            continue
        errors.extend(validate_source(source, path))
        errors.extend(self_promotion_errors(source, app, path))
        sources.append(source)
    if errors:
        raise BuildError("\n".join(errors))
    return sources


def load_host_config(src_root, app):
    """Derived-host config from <src_root>/_hosts/<app>.json, or None.

    {"derive_from": "oryth", "platforms": ["ios"], "min_app_version": "2.0.1",
     "max_impressions_per_user": 20, "cta_hosts": ["apps.apple.com", "ovject.com"], "exclude": ["<item id>"]}
    Only derive_from and platforms are required."""
    path = Path(src_root) / HOSTS_DIR / f"{app}.json"
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            host = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BuildError(f"{path}: cannot read JSON ({exc})")
    errors = []
    if not isinstance(host, dict):
        raise BuildError(f"{path}: must be a JSON object")
    _check_keys(host, ("derive_from", "platforms"), HOST_KEYS, str(path), errors)
    parent = host.get("derive_from")
    if not isinstance(parent, str) or not APP_RE.match(parent) or parent == app:
        errors.append(f"{path}.derive_from: must be another app slug")
    elif (Path(src_root) / HOSTS_DIR / f"{parent}.json").is_file():
        errors.append(f"{path}.derive_from: '{parent}' is itself a derived host; chains are not allowed")
    platforms = host.get("platforms")
    if not isinstance(platforms, list) or not platforms or any(p not in PLATFORMS for p in platforms):
        errors.append(f"{path}.platforms: non-empty list of {list(PLATFORMS)}")
    version = host.get("min_app_version")
    if version is not None and (not isinstance(version, str) or not SEMVER_RE.match(version)):
        errors.append(f"{path}.min_app_version: must be semver like 1.2.3")
    impressions = host.get("max_impressions_per_user")
    if impressions is not None and (not is_int(impressions) or impressions < 1):
        errors.append(f"{path}.max_impressions_per_user: must be an integer >= 1")
    for key in ("cta_hosts", "exclude"):
        value = host.get(key)
        if value is not None and (not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value)):
            errors.append(f"{path}.{key}: must be a list of non-empty strings")
    if errors:
        raise BuildError("\n".join(errors))
    return host


APPLE_STORE_HOSTS = ("apps.apple.com",)
PLAY_STORE_HOSTS = ("play.google.com",)


def retarget_store_cta(cta, store, platforms, app, item_id):
    """The CTA of a derived item, pointed at the store that fits the host app's platforms.

    A store link (App Store or Google Play) is rebuilt from the item's `store` ids, so an Android host does
    not send people to the App Store. Host platforms on one store family give a plain url CTA with the host's
    UTM; platforms on both (a Flutter app on iOS and Android) give `{"action": "store"}`, which the client
    resolves from `store` at runtime. A CTA that is not a store link (a website, Threads) is returned as is.
    Returns None when the needed store id is missing (the item is left out)."""
    url = cta.get("url")
    hostname = (urlsplit(url).hostname or "") if isinstance(url, str) else ""
    if hostname not in APPLE_STORE_HOSTS + PLAY_STORE_HOSTS:
        return copy.deepcopy(cta)
    store = store or {}
    apple = bool(set(platforms) & {"ios", "macos"})
    play = "android" in platforms
    if apple and play:
        if not store.get("ios_app_id") and not store.get("android_package"):
            return None
        return {"action": "store"}
    params = utm_params(url)
    utm = (
        f"utm_source={app}&utm_medium=feedcard&utm_campaign={params.get('utm_campaign', 'feedcard')}"
        f"&utm_content={item_id}"
    )
    if apple:
        if store.get("ios_app_id"):
            return {**cta, "url": f"https://apps.apple.com/app/id{store['ios_app_id']}?{utm}"}
        return copy.deepcopy(cta) if hostname in APPLE_STORE_HOSTS else None
    if play:
        if store.get("android_package"):
            return {**cta, "url": f"https://play.google.com/store/apps/details?id={store['android_package']}&{utm}"}
        return copy.deepcopy(cta) if hostname in PLAY_STORE_HOSTS else None
    return copy.deepcopy(cta)


def derived_sources(src_root, app, host, own_ids):
    """Copies of the parent app's items for a derived host.

    The copy keeps the parent's strings, approval and review gates (JY: approving an item for the parent app
    approves it here too). Host fields replace platforms/min_app_version/max_impressions_per_user and the CTA's
    utm_source becomes this app. Skipped: ids in `exclude`, ids the host defines itself, items about the host
    app, items whose `runs_on` shares no platform with the host's `platforms` (desktop-only apps in an iOS app),
    and items whose CTA host is not in `cta_hosts` (when set)."""
    derived = []
    exclude = set(host.get("exclude") or [])
    cta_hosts = host.get("cta_hosts")
    for source in load_sources(src_root, host["derive_from"]):
        item_id = source["id"]
        if item_id in exclude or item_id in own_ids:
            continue
        if item_id.startswith(f"{app}-") or app in (source.get("tags") or []):
            continue
        # An app that does not run on the host's platforms (a desktop-only app in an iOS app) is not promoted
        # there. An item without `runs_on` (unknown, e.g. a pre-registration page) is kept.
        runs_on = source.get("runs_on")
        if runs_on and not set(runs_on) & set(host["platforms"]):
            continue
        item = copy.deepcopy(source)
        item["platforms"] = list(host["platforms"])
        if host.get("min_app_version") is not None:
            item["min_app_version"] = host["min_app_version"]
        if host.get("max_impressions_per_user") is not None:
            item["max_impressions_per_user"] = host["max_impressions_per_user"]
        cta = retarget_store_cta(item.get("cta") or {}, item.get("store"), host["platforms"], app, item_id)
        if cta is None:
            continue
        item["cta"] = cta
        url = cta.get("url")
        if isinstance(url, str):
            if cta_hosts is not None and (urlsplit(url).hostname or "") not in cta_hosts:
                continue
            cta["url"] = re.sub(r"utm_source=[^&]*", f"utm_source={app}", url)
        derived.append(item)
    return derived


def load_app_sources(src_root, app):
    """The app's own items plus, for a derived host, the items derived from its parent."""
    own = load_sources(src_root, app)
    host = load_host_config(src_root, app)
    if host is None:
        return own
    return own + derived_sources(src_root, app, host, {source["id"] for source in own})


def load_links(src_root, app):
    """Links for `app` from <src_root>/_links/<app>.json ({"links": [...]}), or None.

    The file sits outside src/<app>/ so the item loader never sees it. Absent
    file or an empty array means the output carries no `links` field."""
    path = Path(src_root) / LINKS_DIR / f"{app}.json"
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BuildError(f"{path}: cannot read JSON ({exc})")
    errors = []
    if not isinstance(doc, dict):
        errors.append(f"{path}: must be a JSON object")
    else:
        _check_keys(doc, ("links",), ("links",), str(path), errors)
        if "links" in doc:
            validate_links(doc["links"], f"{path}.links", errors, allow_empty=True)
    if errors:
        raise BuildError("\n".join(errors))
    return normalize_links(doc["links"]) or None


def gate_result(source, locale):
    """'pass', 'fail', 'needs_human', or None when the gate has not run."""
    review = source.get("review")
    if not isinstance(review, dict):
        return None
    entry = review.get(locale)
    if not isinstance(entry, dict):
        return None
    return entry.get("gate")


def item_for_locale(source, locale):
    """Compose one output item; returns (item, used_locale).

    Falls back to the source locale only when the locale has no strings at
    all (validate_source rejects half-filled locales)."""
    strings = source["strings"]
    entry = strings.get(locale)
    used = locale
    if entry is None:
        entry = strings[SOURCE_LOCALE]
        used = SOURCE_LOCALE
    item = {
        "id": source["id"],
        "kind": source["kind"],
        "priority": source["priority"],
        "starts_at": source["starts_at"],
        "ends_at": source["ends_at"],
        "platforms": list(source["platforms"]),
    }
    if source.get("runs_on") is not None:
        item["runs_on"] = list(source["runs_on"])
    if source.get("min_app_version") is not None:
        item["min_app_version"] = source["min_app_version"]
    if source.get("max_impressions_per_user") is not None:
        item["max_impressions_per_user"] = source["max_impressions_per_user"]
    item["title"] = entry["title"]
    item["body"] = entry["body"]
    if source.get("image") is not None:
        item["image"] = dict(source["image"])
    cta = dict(source["cta"])
    cta = {"label": entry["cta_label"], **cta}
    item["cta"] = cta
    item["secondary"] = {"label": entry["secondary_label"], "action": source["secondary"].get("action", "dismiss")}
    item["store"] = source.get("store")
    if source.get("tags") is not None:
        item["tags"] = list(source["tags"])
    item["approval"] = dict(source["approval"])
    return item, used


def build_locale_feed(app, locale, sources, *, generated_at, ttl_hours=DEFAULT_TTL_HOURS,
                      include_pending=False, links=None):
    """Return (feed_dict, report) for one locale. Raises BuildError on lint failure."""
    items = []
    report = {"fallbacks": [], "skipped_pending": [], "gate_failed": []}
    for source in sources:
        if is_pending(source) and not include_pending:
            report["skipped_pending"].append(source["id"])
            continue
        gate = gate_result(source, locale)
        if gate is not None and gate != GATE_PASS:
            # Failed or undecided gate: the item is left out of this locale's
            # file rather than shown in English (§8-2).
            report["gate_failed"].append(f"{source['id']}({gate})")
            continue
        item, used = item_for_locale(source, locale)
        if used != locale:
            report["fallbacks"].append(source["id"])
        items.append(item)
    items.sort(key=lambda entry: (-entry["priority"], entry["id"]))
    feed = {
        "schema_version": SCHEMA_VERSION,
        "app": app,
        "locale": locale,
        "generated_at": generated_at,
        "ttl_hours": ttl_hours,
        "items": items,
    }
    if links:
        feed["links"] = [dict(link) for link in links]
    feed["signature"] = None
    errors = validate_feed(feed, expected_app=app, expected_locale=locale, allow_pending=include_pending)
    if errors:
        raise BuildError(f"{app}/{locale}.json failed validation:\n  " + "\n  ".join(errors))
    return feed, report


def build_app(app, src_root, *, generated_at=None, ttl_hours=DEFAULT_TTL_HOURS,
              include_pending=False, locales=LOCALES):
    """Return {locale: (feed, report)} for every locale."""
    sources = load_app_sources(src_root, app)
    links = load_links(src_root, app)
    generated_at = generated_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if parse_datetime(generated_at) is None:
        raise BuildError(f"--generated-at is not an ISO 8601 date-time: {generated_at}")
    return {
        locale: build_locale_feed(
            app, locale, sources, generated_at=generated_at, ttl_hours=ttl_hours,
            include_pending=include_pending, links=links,
        )
        for locale in locales
    }


def content_key(text):
    """The feed text minus generated_at, for change detection; None when not JSON."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    if isinstance(doc, dict):
        doc = dict(doc)
        doc.pop("generated_at", None)
    return serialize(doc)


def write_feeds(built, app, out_root, *, skip_unchanged=False):
    """Write <out>/<app>/<locale>.json; return (written, unchanged) path lists.

    With skip_unchanged, a file whose content apart from generated_at is
    already identical is left untouched: its generated_at keeps saying when
    the content last changed, and version control sees no churn."""
    out_dir = Path(out_root) / app
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    unchanged = []
    for locale, (feed, _report) in built.items():
        path = out_dir / f"{locale}.json"
        text = serialize(feed)
        if skip_unchanged and path.is_file():
            if content_key(path.read_text(encoding="utf-8")) == content_key(text):
                unchanged.append(path)
                continue
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written, unchanged


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def expected_from_path(path):
    """Infer (app, locale) from <...>/<app>/<locale>.json; None when not inferable."""
    path = Path(path)
    locale = path.stem
    app = path.parent.name
    if locale in LOCALES and APP_RE.match(app):
        return app, locale
    return None, None


def check_files(paths, *, allow_pending):
    failed = 0
    for raw in paths:
        path = Path(raw)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"FAIL {path}: cannot read JSON ({exc})")
            failed += 1
            continue
        app, locale = expected_from_path(path)
        errors = validate_feed(doc, expected_app=app, expected_locale=locale, allow_pending=allow_pending)
        if path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"file size {path.stat().st_size} bytes exceeds {MAX_FILE_BYTES}")
        if errors:
            failed += 1
            print(f"FAIL {path}")
            for error in errors:
                print(f"  - {error}")
        else:
            count = len(doc.get("items", []))
            print(f"ok   {path} ({count} items, {path.stat().st_size} bytes)")
    return failed == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="feed JSON files to validate (with --check)")
    parser.add_argument("--app", action="append",
                        help="app slug to build, e.g. oryth (repeatable; default: every folder under --src)")
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="source root (default: <repo>/src)")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="output root; files go to <out>/<app>/<locale>.json (default: <repo>/v1)")
    parser.add_argument("--check", action="store_true", help="validate only; never write")
    parser.add_argument("--skip-unchanged", action="store_true",
                        help="leave files alone whose content apart from generated_at is unchanged")
    parser.add_argument("--include-pending", action="store_true",
                        help="emit items whose approval is still pending (local preview only)")
    parser.add_argument("--generated-at", help="ISO 8601 UTC time to stamp (default: now)")
    parser.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    args = parser.parse_args(argv)

    if args.files:
        if not args.check:
            parser.error("positional files are only accepted with --check")
        return 0 if check_files(args.files, allow_pending=args.include_pending) else 1

    try:
        apps = args.app or discover_apps(args.src)
    except BuildError as exc:
        print(f"FAIL {exc}")
        return 1

    failed = False
    for app in apps:
        try:
            built = build_app(
                app, args.src, generated_at=args.generated_at, ttl_hours=args.ttl_hours,
                include_pending=args.include_pending,
            )
        except BuildError as exc:
            print(f"FAIL {exc}")
            failed = True
            continue

        for locale, (feed, report) in built.items():
            note = []
            if report["fallbacks"]:
                note.append(f"en fallback: {', '.join(report['fallbacks'])}")
            if report["skipped_pending"]:
                note.append(f"skipped pending: {', '.join(report['skipped_pending'])}")
            if report["gate_failed"]:
                note.append(f"left out, gate not passed: {', '.join(report['gate_failed'])}")
            size = len(serialize(feed).encode("utf-8"))
            print(f"ok   {app}/{locale}.json ({len(feed['items'])} items, {size} bytes){' — ' + '; '.join(note) if note else ''}")

        if args.check:
            continue
        written, unchanged = write_feeds(built, app, args.out, skip_unchanged=args.skip_unchanged)
        suffix = f" ({len(unchanged)} unchanged, left as is)" if unchanged else ""
        print(f"wrote {len(written)} files under {Path(args.out) / app}{suffix}")

    if args.check:
        print("check only; nothing written")
    elif args.include_pending:
        print("note: built with --include-pending; rebuild without it after approval before publishing")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
