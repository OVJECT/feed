#!/usr/bin/env python3
"""clients/test-vectors.json must agree with the reference implementation (clients/reference.py) and, where a
Swift compiler exists, with the Swift core copy (clients/swift/). Runs in CI with the other tests; the Swift part
is skipped on machines without swiftc."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLIENTS = Path(__file__).resolve().parent.parent / "clients"
sys.path.insert(0, str(CLIENTS))
import reference  # noqa: E402

VECTORS = json.loads((CLIENTS / "test-vectors.json").read_text(encoding="utf-8"))


class ReferenceAgainstVectorsTests(unittest.TestCase):
    def test_locale(self):
        for case in VECTORS["locale"]:
            with self.subTest(preferred=case["preferred"]):
                self.assertEqual(reference.feed_locale(case["preferred"]), case["expected"])

    def test_url_safety(self):
        hosts = VECTORS["reference_allowed_hosts"]
        for case in VECTORS["url_safety"]:
            with self.subTest(url=case["url"]):
                self.assertEqual(reference.is_safe_url(case["url"], hosts), case["expected"])

    def test_semver(self):
        for case in VECTORS["semver"]:
            with self.subTest(case=case):
                self.assertEqual(reference.version_at_least(case["version"], case["minimum"]), case["expected"])

    def test_pick(self):
        hosts = VECTORS["reference_allowed_hosts"]
        for case in VECTORS["pick"]:
            with self.subTest(name=case["name"]):
                picked = reference.pick(
                    case["items"], now=case["now"], app_version=case["app_version"],
                    impressions=case["impressions"], host_app=case["host_app"],
                    platform=case["platform"], allowed_hosts=hosts,
                )
                self.assertEqual(picked["id"] if picked else None, case["expected_id"])

    def test_vectors_cover_every_feed_locale(self):
        covered = {case["expected"] for case in VECTORS["locale"]}
        self.assertEqual(covered, set(reference.FEED_LOCALES))


@unittest.skipUnless(shutil.which("swiftc"), "swiftc not available")
class SwiftCoreAgainstVectorsTests(unittest.TestCase):
    def test_swift_core_passes_the_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "ovject-vectors"
            build = subprocess.run(
                ["swiftc", str(CLIENTS / "swift" / "OvjectHouseAdCore.swift"), str(CLIENTS / "swift" / "main.swift"),
                 "-o", str(binary)],
                capture_output=True, text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(CLIENTS / "test-vectors.json")], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
