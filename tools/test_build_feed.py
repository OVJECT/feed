#!/usr/bin/env python3
"""Tests for build_feed.py (run from the repo root: python3 -m unittest discover -s tools -p "test_*.py").

The CommittedSourcesTests at the end read the real src/ folder, so they also act as
the source check that CI runs on every change."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_feed  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "tools" / "fixtures" / "feed-example.ko.json"
FEED_SRC = REPO / "src"
GENERATED_AT = "2026-10-20T00:00:00Z"
LATER = "2026-11-01T00:00:00Z"


def approved_source(item_id="sample-card-001", **overrides):
    source = {
        "id": item_id,
        "kind": "promo",
        "priority": 10,
        "starts_at": "2026-10-20T00:00:00Z",
        "ends_at": "2026-12-01T00:00:00Z",
        "platforms": ["macos", "ios"],
        "min_app_version": "1.0.8",
        "max_impressions_per_user": 3,
        "image": None,
        "cta": {
            "action": "url",
            "url": f"https://ovject.com/oddside?utm_source=testapp&utm_medium=feedcard&utm_campaign=oddside_prereg&utm_content={item_id}",
        },
        "secondary": {"action": "dismiss"},
        "store": None,
        "tags": ["oddside"],
        "approval": {"gate": "nimble-5f-pass", "approved_by": "JY", "approved_at": "2026-10-19T10:00:00Z"},
        "strings": {
            "en": {"title": "Title EN", "body": "Body EN", "cta_label": "Get updates", "secondary_label": "Not now"},
            "ko": {"title": "제목 KO", "body": "본문 KO", "cta_label": "소식 받기", "secondary_label": "나중에"},
        },
    }
    source.update(overrides)
    return source


def source_for_app(app, item_id="sample-card-001", **overrides):
    """approved_source() whose CTA utm_source matches `app` (the lint requires it)."""
    source = approved_source(item_id, **overrides)
    source["cta"]["url"] = source["cta"]["url"].replace("utm_source=testapp", f"utm_source={app}")
    return source


def write_sources(root, app, sources):
    app_dir = Path(root) / app
    app_dir.mkdir(parents=True, exist_ok=True)
    for source in sources:
        (app_dir / f"{source['id']}.json").write_text(
            json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return app_dir


class FallbackTests(unittest.TestCase):
    def test_locale_without_strings_falls_back_to_en(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [approved_source()])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)

        ko_feed, ko_report = built["ko"]
        ja_feed, ja_report = built["ja"]
        self.assertEqual(ko_feed["items"][0]["title"], "제목 KO")
        self.assertEqual(ko_feed["items"][0]["cta"]["label"], "소식 받기")
        self.assertEqual(ko_report["fallbacks"], [])
        self.assertEqual(ja_feed["locale"], "ja")
        self.assertEqual(ja_feed["items"][0]["title"], "Title EN")
        self.assertEqual(ja_feed["items"][0]["secondary"]["label"], "Not now")
        self.assertEqual(ja_report["fallbacks"], ["sample-card-001"])
        self.assertEqual(sorted(built), sorted(build_feed.LOCALES))

    def test_incomplete_locale_strings_are_rejected_not_filled_in(self):
        source = approved_source()
        source["strings"]["ja"] = {"title": "タイトル"}  # body etc. missing
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [source])
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)
        self.assertIn("strings.ja: present but incomplete", str(raised.exception))

    def test_failed_gate_leaves_the_item_out_of_that_locale_only(self):
        source = approved_source()
        source["strings"]["ja"] = {
            "title": "タイトル", "body": "本文", "cta_label": "更新を受け取る", "secondary_label": "あとで",
        }
        source["review"] = {
            "ja": {"gate": "fail", "fields": {"tone": "OFF_BRAND"}},
            "ko": {"gate": "pass"},
            "de": {"gate": "needs_human"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [source])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)
        self.assertEqual(built["ja"][0]["items"], [])
        self.assertEqual(built["ja"][1]["gate_failed"], ["sample-card-001(fail)"])
        self.assertEqual(built["ja"][1]["fallbacks"], [])
        self.assertEqual(built["de"][0]["items"], [], "undecided gate is not shown either")
        self.assertEqual(built["de"][1]["gate_failed"], ["sample-card-001(needs_human)"])
        self.assertEqual(built["ko"][0]["items"][0]["title"], "제목 KO")
        self.assertEqual(built["en"][0]["items"][0]["title"], "Title EN", "no review means not gated yet")
        self.assertEqual(built["fr"][1]["fallbacks"], ["sample-card-001"], "absent locale still falls back")
        self.assertNotIn("review", built["ko"][0]["items"][0])

    def test_review_needs_a_known_gate_value(self):
        source = approved_source(review={"ko": {"gate": "ok"}})
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [source])
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.load_sources(tmp, "testapp")
        self.assertIn("review.ko", str(raised.exception))

    def test_items_sorted_by_priority_then_id(self):
        low = approved_source("aaa-low", priority=1)
        low["cta"]["url"] = low["cta"]["url"].replace("utm_content=sample-card-001", "utm_content=aaa-low")
        high = approved_source("zzz-high", priority=9)
        high["cta"]["url"] = high["cta"]["url"].replace("utm_content=sample-card-001", "utm_content=zzz-high")
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [low, high])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)
        self.assertEqual([item["id"] for item in built["en"][0]["items"]], ["zzz-high", "aaa-low"])

    def test_notes_and_strings_are_not_emitted(self):
        source = approved_source(notes="internal remark")
        source["gate_context"] = {"app_summary": "evidence for the gate", "source_excerpts": ["quote"]}
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [source])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)
        item = built["en"][0]["items"][0]
        self.assertNotIn("notes", item)
        self.assertNotIn("strings", item)
        self.assertNotIn("gate_context", item)
        self.assertEqual(item["approval"]["approved_by"], "JY")


class PendingTests(unittest.TestCase):
    def pending_source(self):
        return approved_source(approval={"gate": "pending", "approved_by": "", "approved_at": ""})

    def test_pending_items_are_dropped_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [self.pending_source()])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)
        feed, report = built["en"]
        self.assertEqual(feed["items"], [])
        self.assertEqual(report["skipped_pending"], ["sample-card-001"])

    def test_pending_items_are_emitted_with_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [self.pending_source()])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT, include_pending=True)
        feed, report = built["en"]
        self.assertEqual(len(feed["items"]), 1)
        self.assertEqual(feed["items"][0]["approval"]["gate"], "pending")
        self.assertEqual(report["skipped_pending"], [])

    def test_pending_feed_file_fails_strict_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [self.pending_source()])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT, include_pending=True)
        errors = build_feed.validate_feed(built["en"][0])
        self.assertTrue(any("pending" in error for error in errors))
        self.assertEqual(build_feed.validate_feed(built["en"][0], allow_pending=True), [])


class ValidationFailureTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def errors_after(self, mutate):
        doc = copy.deepcopy(self.doc)
        mutate(doc)
        return build_feed.validate_feed(doc)

    def assert_error(self, mutate, fragment):
        errors = self.errors_after(mutate)
        self.assertTrue(
            any(fragment in error for error in errors),
            f"expected an error containing {fragment!r}, got {errors}",
        )

    def test_example_file_passes(self):
        self.assertEqual(build_feed.validate_feed(self.doc, expected_app="kairo", expected_locale="ko"), [])

    def test_missing_utm_is_rejected(self):
        def mutate(doc):
            doc["items"][0]["cta"]["url"] = "https://ovject.com/oddside?utm_source=kairo"
        self.assert_error(mutate, "utm_source, utm_medium=feedcard")

    def test_http_url_is_rejected(self):
        def mutate(doc):
            doc["items"][0]["cta"]["url"] = doc["items"][0]["cta"]["url"].replace("https://", "http://")
        self.assert_error(mutate, "must start with https://")

    def test_utm_source_must_match_app(self):
        def mutate(doc):
            doc["items"][0]["cta"]["url"] = doc["items"][0]["cta"]["url"].replace("utm_source=kairo", "utm_source=other")
        self.assert_error(mutate, "utm_source must equal app")

    def test_utm_content_must_match_item_id(self):
        def mutate(doc):
            doc["items"][0]["cta"]["url"] = doc["items"][0]["cta"]["url"].replace(
                "utm_content=oddside-updates-2026w44", "utm_content=something-else"
            )
        self.assert_error(mutate, "utm_content must equal item id")

    def test_title_too_long_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].__setitem__("title", "x" * 41), "title: must be 1..40")

    def test_body_too_long_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].__setitem__("body", "x" * 121), "body: must be 1..120")

    def test_label_too_long_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0]["cta"].__setitem__("label", "x" * 17), "cta.label: must be 1..16")

    def test_unknown_kind_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].__setitem__("kind", "banner"), "kind: must be one of")

    def test_reversed_dates_are_rejected(self):
        def mutate(doc):
            doc["items"][0]["starts_at"], doc["items"][0]["ends_at"] = doc["items"][0]["ends_at"], doc["items"][0]["starts_at"]
        self.assert_error(mutate, "ends_at must be after starts_at")

    def test_bad_date_format_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].__setitem__("starts_at", "2026-10-26"), "starts_at: must be an ISO 8601")
        self.assert_error(lambda doc: doc.__setitem__("generated_at", "yesterday"), "generated_at: must be an ISO 8601")

    def test_unknown_platform_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].__setitem__("platforms", ["ios", "web"]), "unknown platform 'web'")

    def test_more_than_ten_items_is_rejected(self):
        def mutate(doc):
            template = doc["items"][0]
            doc["items"] = []
            for index in range(11):
                item = copy.deepcopy(template)
                item["id"] = f"item-{index:02d}"
                item["cta"]["url"] = template["cta"]["url"].replace("utm_content=oddside-updates-2026w44", f"utm_content=item-{index:02d}")
                doc["items"].append(item)
        self.assert_error(mutate, "at most 10 items")

    def test_oversized_feed_is_rejected(self):
        def mutate(doc):
            doc["items"][0]["body"] = "x" * 120
            template = doc["items"][0]
            doc["items"] = []
            for index in range(10):
                item = copy.deepcopy(template)
                item["id"] = f"item-{index:02d}"
                item["cta"]["url"] = template["cta"]["url"].replace("utm_content=oddside-updates-2026w44", f"utm_content=item-{index:02d}")
                item["tags"] = [f"tag-{n:02d}-{'y' * 26}" for n in range(60)]
                doc["items"].append(item)
        self.assert_error(mutate, "exceeds 20480")

    def test_missing_approval_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].pop("approval"), "missing required key 'approval'")

    def test_secondary_must_be_dismiss(self):
        self.assert_error(lambda doc: doc["items"][0]["secondary"].__setitem__("action", "url"), "secondary.action: must be 'dismiss'")

    def test_store_action_requires_store_object(self):
        def mutate(doc):
            doc["items"][0]["cta"] = {"label": "Open store", "action": "store"}
            doc["items"][0]["store"] = None
        self.assert_error(mutate, "store: required object when cta.action=store")

    def test_unknown_property_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].__setitem__("script", "alert(1)"), "unknown key 'script'")
        self.assert_error(lambda doc: doc.__setitem__("extra", 1), "unknown key 'extra'")

    def test_markup_in_text_is_rejected(self):
        self.assert_error(lambda doc: doc["items"][0].__setitem__("body", "<b>bold</b>"), "HTML/markup is not allowed")

    def test_ttl_out_of_range_is_rejected(self):
        self.assert_error(lambda doc: doc.__setitem__("ttl_hours", 0), "ttl_hours: must be an integer 1..168")
        self.assert_error(lambda doc: doc.__setitem__("ttl_hours", 169), "ttl_hours: must be an integer 1..168")

    def test_wrong_schema_version_is_rejected(self):
        self.assert_error(lambda doc: doc.__setitem__("schema_version", 2), "schema_version: must be 1")

    def test_path_mismatch_is_reported(self):
        errors = build_feed.validate_feed(self.doc, expected_app="oryth", expected_locale="en")
        self.assertTrue(any("does not match path app" in error for error in errors))
        self.assertTrue(any("does not match path locale" in error for error in errors))

    def test_duplicate_ids_are_rejected(self):
        def mutate(doc):
            doc["items"].append(copy.deepcopy(doc["items"][0]))
        self.assert_error(mutate, "duplicate id")

    def test_image_rules(self):
        self.assert_error(lambda doc: doc["items"][0]["image"].__setitem__("url", "http://x/y.png"), "image.url: must start with https://")
        self.assert_error(lambda doc: doc["items"][0]["image"].__setitem__("alt", ""), "image.alt: must be 1..120")


class SourceValidationTests(unittest.TestCase):
    def test_source_id_must_match_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "testapp"
            app_dir.mkdir()
            (app_dir / "other-name.json").write_text(json.dumps(approved_source()), encoding="utf-8")
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.load_sources(tmp, "testapp")
        self.assertIn("must equal the file name", str(raised.exception))

    def test_source_without_en_strings_is_rejected(self):
        source = approved_source()
        del source["strings"]["en"]
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [source])
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.load_sources(tmp, "testapp")
        self.assertIn("strings.en", str(raised.exception))

    def test_built_feed_lint_failure_raises(self):
        source = approved_source()
        source["cta"]["url"] = "https://ovject.com/no-utm"
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [source])
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)
        self.assertIn("utm", str(raised.exception))

    def test_item_about_the_target_app_itself_is_rejected(self):
        """JY rule (2026-10-19): an app never introduces itself. Tagged with the app,
        or id prefixed '<app>-', is an error for that app's feed; fine for another app."""
        tagged = approved_source(tags=["testapp", "news"])
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [tagged])
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.load_sources(tmp, "testapp")
        self.assertIn("tags contain 'testapp'", str(raised.exception))
        self.assertIn("does not introduce itself", str(raised.exception))

        prefixed = source_for_app("testapp", "testapp-update-2026w50", tags=["other"])
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [prefixed])
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.load_sources(tmp, "testapp")
        self.assertIn("starts with 'testapp-'", str(raised.exception))

        # The same item is allowed in another app's feed (utm_source must match that app).
        for_other = source_for_app("otherapp", "testapp-update-2026w50", tags=["testapp"])
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "otherapp", [for_other])
            built = build_feed.build_app("otherapp", tmp, generated_at=GENERATED_AT)
        self.assertEqual(built["en"][0]["items"][0]["id"], "testapp-update-2026w50")


class RunsOnTests(unittest.TestCase):
    """`runs_on` = platforms the promoted app itself runs on (optional, passed through);
    `platforms` = host app platforms on which the item is shown."""

    def test_runs_on_passes_through_when_present_and_stays_absent_otherwise(self):
        with_it = approved_source(runs_on=["ios", "android"])
        without = approved_source("other-card-002")
        without["cta"]["url"] = without["cta"]["url"].replace("utm_content=sample-card-001", "utm_content=other-card-002")
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [with_it, without])
            built = build_feed.build_app("testapp", tmp, generated_at=GENERATED_AT)
        feed, _report = built["en"]
        by_id = {item["id"]: item for item in feed["items"]}
        self.assertEqual(by_id["sample-card-001"]["runs_on"], ["ios", "android"])
        self.assertEqual(by_id["sample-card-001"]["platforms"], ["macos", "ios"], "platforms is untouched")
        self.assertNotIn("runs_on", by_id["other-card-002"])
        self.assertEqual(build_feed.validate_feed(feed, expected_app="testapp", expected_locale="en"), [])

    def test_runs_on_rejects_unknown_platform_empty_or_duplicate_values(self):
        for bad, fragment in (
            (["ios", "tvos"], "unknown platform 'tvos'"),
            ([], "non-empty array"),
            ("ios", "non-empty array"),
            (["ios", "ios"], "must be unique"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                write_sources(tmp, "testapp", [approved_source(runs_on=bad)])
                with self.assertRaises(build_feed.BuildError) as raised:
                    build_feed.load_sources(tmp, "testapp")
            self.assertIn("runs_on", str(raised.exception))
            self.assertIn(fragment, str(raised.exception))
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["items"][0]["runs_on"] = ["web", "windows"]
        self.assertEqual(build_feed.validate_feed(doc, expected_app="kairo", expected_locale="ko"), [])
        doc["items"][0]["runs_on"] = ["desktop"]
        self.assertTrue(any("runs_on: unknown platform 'desktop'" in error for error in build_feed.validate_feed(doc)))


GOOD_LINKS = [
    {"kind": "website", "url": "https://ovject.github.io/Website/"},
    {"kind": "appstore", "url": "https://apps.apple.com/us/developer/junyoung-lee/id1501486371"},
    {"kind": "support", "label": "Help", "url": "https://ovject.github.io/Website/oryth-support.html"},
    {"kind": "privacy", "url": "https://ovject.github.io/Website/oryth_privacy_policy_en.html"},
]


def write_links(root, app, doc):
    links_dir = Path(root) / "_links"
    links_dir.mkdir(parents=True, exist_ok=True)
    (links_dir / f"{app}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


class LinksTests(unittest.TestCase):
    """Feed-level `links`: src/_links/<app>.json -> the same links in all 10 locale files."""

    def build(self, links_doc=None, app="testapp"):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, app, [approved_source()])
            if links_doc is not None:
                write_links(tmp, app, links_doc)
            return build_feed.build_app(app, tmp, generated_at=GENERATED_AT)

    def load_error(self, links):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [approved_source()])
            write_links(tmp, "testapp", {"links": links})
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.load_links(tmp, "testapp")
        return str(raised.exception)

    def test_links_reach_every_locale_in_order_with_default_labels(self):
        built = self.build({"links": GOOD_LINKS})
        self.assertEqual(sorted(built), sorted(build_feed.LOCALES))
        expected = [
            {"kind": "website", "label": "Website", "url": "https://ovject.github.io/Website/"},
            {"kind": "appstore", "label": "App Store", "url": "https://apps.apple.com/us/developer/junyoung-lee/id1501486371"},
            {"kind": "support", "label": "Help", "url": "https://ovject.github.io/Website/oryth-support.html"},
            {"kind": "privacy", "label": "Privacy", "url": "https://ovject.github.io/Website/oryth_privacy_policy_en.html"},
        ]
        for locale, (feed, _report) in built.items():
            self.assertEqual(feed["links"], expected, locale)
            self.assertEqual(build_feed.validate_feed(feed, expected_app="testapp", expected_locale=locale), [], locale)
        # the item UTM rule does not apply to links: none of them carries utm_*
        self.assertFalse(any("utm_" in link["url"] for link in expected))

    def test_no_links_file_or_empty_array_omits_the_field(self):
        for links_doc in (None, {"links": []}):
            built = self.build(links_doc)
            for locale, (feed, _report) in built.items():
                self.assertNotIn("links", feed, f"{links_doc} {locale}")
                self.assertEqual(build_feed.validate_feed(feed, expected_app="testapp", expected_locale=locale), [])

    def test_links_directory_is_not_an_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "testapp", [approved_source()])
            write_links(tmp, "testapp", {"links": GOOD_LINKS})
            self.assertEqual(build_feed.discover_apps(tmp), ["testapp"])

    def test_cli_builds_links_into_the_written_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            out = Path(tmp) / "out"
            write_sources(src, "testapp", [approved_source()])
            write_links(src, "testapp", {"links": GOOD_LINKS})
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = build_feed.main(["--src", str(src), "--out", str(out), "--generated-at", GENERATED_AT])
            self.assertEqual(code, 0, stdout.getvalue())
            doc = json.loads((out / "testapp" / "th.json").read_text(encoding="utf-8"))
            self.assertEqual([link["kind"] for link in doc["links"]], ["website", "appstore", "support", "privacy"])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(build_feed.main(["--check", str(out / "testapp" / "th.json")]), 0)

    def test_rejects_non_https_url(self):
        self.assertIn("https://", self.load_error([{"kind": "website", "url": "http://ovject.com/"}]))

    def test_rejects_host_not_allowed_for_the_kind(self):
        message = self.load_error([{"kind": "website", "url": "https://example.com/"}])
        self.assertIn("host 'example.com' is not allowed for kind 'website'", message)
        self.assertIn("not allowed", self.load_error([{"kind": "appstore", "url": "https://ovject.com/"}]))
        # look-alike and user-info tricks
        self.assertIn("not allowed", self.load_error([{"kind": "website", "url": "https://ovject.com.evil.test/"}]))
        self.assertIn("not allowed", self.load_error([{"kind": "website", "url": "https://notovject.com/"}]))
        self.assertIn("user info", self.load_error([{"kind": "website", "url": "https://ovject.com@evil.test/"}]))

    def test_allowed_hosts_accept_subdomains_of_the_listed_host(self):
        links = [
            {"kind": "youtube", "url": "https://www.youtube.com/@ovject"},
            {"kind": "x", "url": "https://x.com/ovject"},
            {"kind": "discord", "url": "https://discord.gg/abc"},
            {"kind": "github", "url": "https://github.com/OVJECT"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            write_links(tmp, "testapp", {"links": links})
            self.assertEqual(len(build_feed.load_links(tmp, "testapp")), 4)

    def test_six_links_with_www_social_hosts_keep_their_order(self):
        """The OVJECT row: website, store, socials (www. hosts), then support and privacy."""
        links = [
            {"kind": "website", "url": "https://ovject.com/"},
            {"kind": "appstore", "url": "https://apps.apple.com/us/developer/junyoung-lee/id1501486371"},
            {"kind": "instagram", "url": "https://www.instagram.com/ovject.official/"},
            {"kind": "threads", "url": "https://www.threads.com/@ovject.official"},
            {"kind": "support", "url": "https://ovject.com/oryth-support.html"},
            {"kind": "privacy", "url": "https://ovject.com/oryth_privacy_policy_en.html"},
        ]
        built = self.build({"links": links})
        for locale, (feed, _report) in built.items():
            self.assertEqual([link["kind"] for link in feed["links"]],
                             ["website", "appstore", "instagram", "threads", "support", "privacy"], locale)
            self.assertEqual([link["label"] for link in feed["links"]],
                             ["Website", "App Store", "Instagram", "Threads", "Support", "Privacy"], locale)
            self.assertEqual([link["url"] for link in feed["links"]], [link["url"] for link in links], locale)
            self.assertEqual(build_feed.validate_feed(feed, expected_app="testapp", expected_locale=locale), [], locale)
        # a www. host is fine for its own service only
        self.assertIn("not allowed", self.load_error([{"kind": "instagram", "url": "https://www.threads.com/@ovject.official"}]))

    def test_rejects_duplicate_url(self):
        message = self.load_error([
            {"kind": "website", "url": "https://ovject.com/"},
            {"kind": "support", "url": "https://ovject.com/"},
        ])
        self.assertIn("duplicate url", message)

    def test_rejects_unknown_kind(self):
        self.assertIn("unknown kind 'myspace'", self.load_error([{"kind": "myspace", "url": "https://ovject.com/"}]))

    def test_rejects_more_than_eight_links(self):
        links = [{"kind": "website", "url": f"https://ovject.com/p{index}"} for index in range(9)]
        self.assertIn("at most 8 links", self.load_error(links))
        eight = links[:8]
        with tempfile.TemporaryDirectory() as tmp:
            write_links(tmp, "testapp", {"links": eight})
            self.assertEqual(len(build_feed.load_links(tmp, "testapp")), 8)

    def test_rejects_bad_label_extra_key_and_bad_file_shape(self):
        self.assertIn("label", self.load_error([{"kind": "website", "label": "홈페이지", "url": "https://ovject.com/"}]))
        self.assertIn("label", self.load_error([{"kind": "website", "label": "x" * 25, "url": "https://ovject.com/"}]))
        self.assertIn("unknown key 'rel'", self.load_error([{"kind": "website", "url": "https://ovject.com/", "rel": "me"}]))
        with tempfile.TemporaryDirectory() as tmp:
            write_links(tmp, "testapp", {"links": GOOD_LINKS, "extra": 1})
            with self.assertRaises(build_feed.BuildError) as raised:
                build_feed.load_links(tmp, "testapp")
            self.assertIn("unknown key 'extra'", str(raised.exception))
            write_links(tmp, "testapp", [])
            with self.assertRaises(build_feed.BuildError):
                build_feed.load_links(tmp, "testapp")

    def test_feed_level_validation_catches_hand_edited_output(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["links"] = [{"kind": "website", "label": "Website", "url": "https://ovject.com/"}]
        self.assertEqual(build_feed.validate_feed(doc, expected_app="kairo", expected_locale="ko"), [])
        doc["links"] = []
        self.assertTrue(any("non-empty array" in error for error in build_feed.validate_feed(doc)))
        doc["links"] = [{"kind": "website", "url": "https://example.com/"}]
        self.assertTrue(any("not allowed" in error for error in build_feed.validate_feed(doc)))

    def test_committed_links_files_build_into_every_locale(self):
        links_dir = FEED_SRC / "_links"
        for path in sorted(links_dir.glob("*.json")) if links_dir.is_dir() else []:
            app = path.stem
            links = build_feed.load_links(FEED_SRC, app)
            self.assertTrue(links, f"{path.name} must hold at least one link")
            built = build_feed.build_app(app, FEED_SRC, generated_at=GENERATED_AT)
            for locale, (feed, _report) in built.items():
                self.assertEqual(feed["links"], links, f"{app}/{locale}")


class CliTests(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = build_feed.main(argv)
        return code, out.getvalue()

    def test_cli_writes_ten_locale_files_and_check_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            out = Path(tmp) / "out"
            write_sources(src, "testapp", [approved_source()])
            code, text = self.run_main(["--app", "testapp", "--src", str(src), "--out", str(out), "--generated-at", GENERATED_AT])
            self.assertEqual(code, 0, text)
            files = sorted((out / "testapp").glob("*.json"))
            self.assertEqual([path.stem for path in files], sorted(build_feed.LOCALES))
            for path in files:
                self.assertLessEqual(path.stat().st_size, build_feed.MAX_FILE_BYTES)
            code, text = self.run_main(["--check", *map(str, files)])
            self.assertEqual(code, 0, text)
            self.assertIn("ok   ", text)

    def test_cli_check_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "en.json"
            bad.write_text('{"schema_version": 1}', encoding="utf-8")
            code, text = self.run_main(["--check", str(bad)])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", text)

    def test_cli_check_mode_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            write_sources(src, "testapp", [approved_source()])
            code, text = self.run_main(["--app", "testapp", "--src", str(src), "--check"])
            self.assertEqual(code, 0, text)
            self.assertFalse((Path(tmp) / "testapp").exists())
            self.assertIn("nothing written", text)

    def test_example_file_passes_cli_check(self):
        code, text = self.run_main(["--check", str(EXAMPLE)])
        self.assertEqual(code, 0, text)

    def test_cli_without_app_builds_every_app_under_src(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            out = Path(tmp) / "out"
            write_sources(src, "appone", [source_for_app("appone")])
            write_sources(src, "apptwo", [source_for_app("apptwo")])
            (src / "not-an-app.txt").write_text("ignored", encoding="utf-8")
            code, text = self.run_main(["--src", str(src), "--out", str(out), "--generated-at", GENERATED_AT])
            self.assertEqual(code, 0, text)
            self.assertEqual(sorted(path.name for path in out.iterdir()), ["appone", "apptwo"])
            self.assertEqual(len(list((out / "apptwo").glob("*.json"))), len(build_feed.LOCALES))
            self.assertIn("ok   appone/en.json", text)
            self.assertIn("ok   apptwo/en.json", text)

    def test_cli_reports_a_missing_source_root(self):
        code, text = self.run_main(["--src", "/nonexistent/src", "--out", "/nonexistent/out"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", text)
        self.assertIn("source root not found", text)

    def test_cli_check_without_app_lints_every_app_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            out = Path(tmp) / "out"
            write_sources(src, "appone", [source_for_app("appone")])
            code, text = self.run_main(["--src", str(src), "--out", str(out), "--check"])
            self.assertEqual(code, 0, text)
            self.assertFalse(out.exists())
            self.assertIn("nothing written", text)

    def test_skip_unchanged_keeps_files_whose_content_did_not_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            out = Path(tmp) / "out"
            write_sources(src, "appone", [source_for_app("appone")])
            code, text = self.run_main(["--src", str(src), "--out", str(out), "--generated-at", GENERATED_AT])
            self.assertEqual(code, 0, text)
            first_en = (out / "appone" / "en.json").read_text(encoding="utf-8")

            # Same sources, later stamp: nothing is rewritten, generated_at stays.
            code, text = self.run_main(["--src", str(src), "--out", str(out), "--generated-at", LATER, "--skip-unchanged"])
            self.assertEqual(code, 0, text)
            self.assertEqual((out / "appone" / "en.json").read_text(encoding="utf-8"), first_en)
            self.assertIn(f"wrote 0 files under {out / 'appone'} ({len(build_feed.LOCALES)} unchanged, left as is)", text)

            # Only the English copy changes: en and the locales that fall back to it
            # get the new stamp; ko, which has its own strings, is left alone.
            changed = source_for_app("appone")
            changed["strings"]["en"]["title"] = "New title EN"
            write_sources(src, "appone", [changed])
            code, text = self.run_main(["--src", str(src), "--out", str(out), "--generated-at", LATER, "--skip-unchanged"])
            self.assertEqual(code, 0, text)
            en = json.loads((out / "appone" / "en.json").read_text(encoding="utf-8"))
            ko = json.loads((out / "appone" / "ko.json").read_text(encoding="utf-8"))
            self.assertEqual(en["generated_at"], LATER)
            self.assertEqual(en["items"][0]["title"], "New title EN")
            self.assertEqual(ko["generated_at"], GENERATED_AT)
            self.assertIn(f"wrote {len(build_feed.LOCALES) - 1} files under {out / 'appone'} (1 unchanged, left as is)", text)

            # Without the flag every file is rewritten, stamp included.
            code, text = self.run_main(["--src", str(src), "--out", str(out), "--generated-at", LATER])
            self.assertEqual(code, 0, text)
            ko = json.loads((out / "appone" / "ko.json").read_text(encoding="utf-8"))
            self.assertEqual(ko["generated_at"], LATER)


class DiscoverAppsTests(unittest.TestCase):
    def test_discover_apps_lists_app_folders_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "oryth").mkdir()
            (Path(tmp) / "kairo").mkdir()
            (Path(tmp) / "Not Valid").mkdir()
            (Path(tmp) / "README.md").write_text("x", encoding="utf-8")
            self.assertEqual(build_feed.discover_apps(tmp), ["kairo", "oryth"])

    def test_discover_apps_rejects_missing_or_empty_root(self):
        with self.assertRaises(build_feed.BuildError):
            build_feed.discover_apps("/nonexistent/src")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(build_feed.BuildError):
                build_feed.discover_apps(tmp)

    def test_content_key_ignores_generated_at_only(self):
        a = build_feed.serialize({"schema_version": 1, "generated_at": GENERATED_AT, "items": []})
        b = build_feed.serialize({"schema_version": 1, "generated_at": LATER, "items": []})
        c = build_feed.serialize({"schema_version": 1, "generated_at": LATER, "items": [{"id": "x"}]})
        self.assertEqual(build_feed.content_key(a), build_feed.content_key(b))
        self.assertNotEqual(build_feed.content_key(a), build_feed.content_key(c))
        self.assertIsNone(build_feed.content_key("not json"))


class CommittedSourcesTests(unittest.TestCase):
    """Every item under src/ must build and lint clean. CI runs this on each change,
    so these tests describe rules, not the current item list."""

    def test_src_has_at_least_one_app(self):
        self.assertTrue(build_feed.discover_apps(FEED_SRC))

    def test_every_item_carries_all_ten_locales_within_limits(self):
        """OVJECT rule (2026-10-19): every item is written by hand in all 10 locales; no en fallback."""
        for app in build_feed.discover_apps(FEED_SRC):
            for source in build_feed.load_sources(FEED_SRC, app):
                label = f"{app}/{source['id']}"
                self.assertEqual(sorted(source["strings"]), sorted(build_feed.LOCALES), label)
                en = source["strings"]["en"]
                for locale in build_feed.LOCALES:
                    entry = source["strings"][locale]
                    self.assertTrue(build_feed.complete_strings(entry), f"{label} {locale}")
                    self.assertLessEqual(len(entry["title"]), build_feed.TITLE_MAX, f"{label} {locale} title")
                    self.assertLessEqual(len(entry["body"]), build_feed.BODY_MAX, f"{label} {locale} body")
                    self.assertLessEqual(len(entry["cta_label"]), build_feed.LABEL_MAX, f"{label} {locale} cta")
                    self.assertLessEqual(len(entry["secondary_label"]), build_feed.LABEL_MAX, f"{label} {locale} secondary")
                    if locale != "en":
                        self.assertNotEqual(entry["body"], en["body"], f"{label} {locale} must not reuse the English body")

    def test_default_build_publishes_only_approved_items_whose_gate_passed(self):
        """What CI publishes: pending items dropped, a locale whose gate is not pass left out, strict lint."""
        for app in build_feed.discover_apps(FEED_SRC):
            sources = build_feed.load_app_sources(FEED_SRC, app)
            built = build_feed.build_app(app, FEED_SRC, generated_at=GENERATED_AT)
            self.assertEqual(sorted(built), sorted(build_feed.LOCALES))
            pending = sorted(source["id"] for source in sources if build_feed.is_pending(source))
            for locale, (feed, report) in built.items():
                label = f"{app}/{locale}"
                self.assertEqual(build_feed.validate_feed(feed, expected_app=app, expected_locale=locale), [], label)
                self.assertEqual(sorted(report["skipped_pending"]), pending, label)
                self.assertEqual(report["fallbacks"], [], f"{label}: every locale is written, nothing falls back")
                expected = [
                    source for source in sources
                    if not build_feed.is_pending(source)
                    and build_feed.gate_result(source, locale) in (None, build_feed.GATE_PASS)
                ]
                expected.sort(key=lambda source: (-source["priority"], source["id"]))
                self.assertEqual([item["id"] for item in feed["items"]], [source["id"] for source in expected], label)
                for item, source in zip(feed["items"], expected):
                    self.assertEqual(item["title"], source["strings"][locale]["title"], label)
                    self.assertTrue(item["approval"]["approved_by"], label)
                    for hidden in ("review", "notes", "gate_context", "strings"):
                        self.assertNotIn(hidden, item, label)

    def test_preview_build_with_pending_covers_every_gated_item(self):
        for app in build_feed.discover_apps(FEED_SRC):
            sources = build_feed.load_app_sources(FEED_SRC, app)
            built = build_feed.build_app(app, FEED_SRC, generated_at=GENERATED_AT, include_pending=True)
            for locale, (feed, report) in built.items():
                label = f"{app}/{locale}"
                self.assertEqual(
                    build_feed.validate_feed(feed, expected_app=app, expected_locale=locale, allow_pending=True), [], label
                )
                self.assertEqual(report["skipped_pending"], [], label)
                ids = [item["id"] for item in feed["items"]]
                for source in sources:
                    gate = build_feed.gate_result(source, locale)
                    if gate in (None, build_feed.GATE_PASS):
                        self.assertIn(source["id"], ids, f"{label} {source['id']}")
                    else:
                        self.assertNotIn(source["id"], ids, f"{label} {source['id']} gate={gate}")
                        self.assertIn(f"{source['id']}({gate})", report["gate_failed"], label)


def write_host(root, app, **config):
    hosts = Path(root) / "_hosts"
    hosts.mkdir(parents=True, exist_ok=True)
    doc = {"derive_from": "parentapp", "platforms": ["ios"]}
    doc.update(config)
    (hosts / f"{app}.json").write_text(json.dumps(doc), encoding="utf-8")


class DerivedHostTests(unittest.TestCase):
    """src/_hosts/<app>.json: the host's feed is built from another app's items."""

    def build(self, tmp, **config):
        write_host(tmp, "hostapp", **config)
        return build_feed.build_app("hostapp", tmp, generated_at=GENERATED_AT)

    def test_items_are_copied_with_host_fields_and_inherited_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [source_for_app("parentapp", "promo-a")])
            built = self.build(tmp, min_app_version="2.0.1", max_impressions_per_user=20)
        feed, _ = built["en"]
        self.assertEqual(feed["app"], "hostapp")
        item = feed["items"][0]
        self.assertEqual(item["id"], "promo-a")
        self.assertEqual(item["platforms"], ["ios"])
        self.assertEqual(item["min_app_version"], "2.0.1")
        self.assertEqual(item["max_impressions_per_user"], 20)
        self.assertIn("utm_source=hostapp", item["cta"]["url"])
        self.assertNotIn("utm_source=parentapp", item["cta"]["url"])
        self.assertEqual(item["approval"]["approved_by"], "JY")
        self.assertEqual(build_feed.validate_feed(feed, expected_app="hostapp", expected_locale="en"), [])

    def test_pending_parent_items_stay_out(self):
        pending = source_for_app("parentapp", "promo-b", approval={"gate": "pending", "approved_by": "", "approved_at": ""})
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [pending])
            feed, report = self.build(tmp)["en"]
        self.assertEqual(feed["items"], [])
        self.assertEqual(report["skipped_pending"], ["promo-b"])

    def test_the_host_never_introduces_itself(self):
        about_host = source_for_app("parentapp", "promo-c", tags=["hostapp"])
        prefixed = source_for_app("parentapp", "hostapp-intro")
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [about_host, prefixed, source_for_app("parentapp", "promo-a")])
            feed, _ = self.build(tmp)["en"]
        self.assertEqual([item["id"] for item in feed["items"]], ["promo-a"])

    def test_apps_that_do_not_run_on_the_host_platform_stay_out(self):
        desktop = source_for_app("parentapp", "promo-mac", runs_on=["macos"])
        android = source_for_app("parentapp", "promo-android", runs_on=["android"])
        both = source_for_app("parentapp", "promo-both", runs_on=["macos", "ios"])
        unknown = source_for_app("parentapp", "promo-unknown")  # no runs_on: kept
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [desktop, android, both, unknown])
            feed, _ = self.build(tmp)["en"]
        self.assertEqual(sorted(item["id"] for item in feed["items"]), ["promo-both", "promo-unknown"])

    def test_exclude_and_cta_hosts(self):
        play = source_for_app("parentapp", "promo-play")
        play["cta"]["url"] = play["cta"]["url"].replace("https://ovject.com", "https://play.google.com")
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [play, source_for_app("parentapp", "promo-a"), source_for_app("parentapp", "promo-x")])
            feed, _ = self.build(tmp, cta_hosts=["ovject.com"], exclude=["promo-x"])["en"]
        self.assertEqual([item["id"] for item in feed["items"]], ["promo-a"])

    def test_an_own_item_with_the_same_id_wins(self):
        own = source_for_app("hostapp", "promo-a", priority=99)
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [source_for_app("parentapp", "promo-a")])
            write_sources(tmp, "hostapp", [own])
            feed, _ = self.build(tmp)["en"]
        self.assertEqual([(item["id"], item["priority"]) for item in feed["items"]], [("promo-a", 99)])

    def test_discovery_lists_host_only_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [source_for_app("parentapp")])
            write_host(tmp, "hostapp")
            self.assertEqual(build_feed.discover_apps(tmp), ["hostapp", "parentapp"])

    def test_bad_host_config_is_rejected(self):
        cases = [
            {"derive_from": "hostapp"},               # itself
            {"platforms": ["windows"]},               # unknown platform
            {"platforms": []},                        # empty
            {"min_app_version": "2.0"},               # not semver
            {"max_impressions_per_user": 0},
            {"cta_hosts": "ovject.com"},              # not a list
            {"surprise": 1},                          # unknown key
        ]
        for config in cases:
            with self.subTest(config=config), tempfile.TemporaryDirectory() as tmp:
                write_sources(tmp, "parentapp", [source_for_app("parentapp")])
                write_host(tmp, "hostapp", **config)
                with self.assertRaises(build_feed.BuildError):
                    build_feed.build_app("hostapp", tmp, generated_at=GENERATED_AT)

    def test_chains_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_sources(tmp, "parentapp", [source_for_app("parentapp")])
            write_host(tmp, "parentapp", derive_from="grandparent")
            write_host(tmp, "hostapp")
            with self.assertRaises(build_feed.BuildError):
                build_feed.build_app("hostapp", tmp, generated_at=GENERATED_AT)


class CommittedHostTests(unittest.TestCase):
    def test_every_committed_host_builds_and_passes_the_strict_check(self):
        for path in sorted((FEED_SRC / "_hosts").glob("*.json")):
            app = path.stem
            built = build_feed.build_app(app, FEED_SRC, generated_at=GENERATED_AT)
            for locale, (feed, _report) in built.items():
                self.assertEqual(
                    build_feed.validate_feed(feed, expected_app=app, expected_locale=locale), [], f"{app}/{locale}"
                )
                for item in feed["items"]:
                    self.assertNotIn(app, item.get("tags") or [], f"{app} introduces itself: {item['id']}")


if __name__ == "__main__":
    unittest.main()
