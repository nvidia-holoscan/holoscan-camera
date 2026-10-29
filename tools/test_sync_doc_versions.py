# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Dependency docs track selected inputs without changing other version domains."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.sync_doc_versions import render, rewrite, synchronize


def marked(key, content="stale\n"):
    return f"<!-- module-docs:{key} -->\n{content}<!-- /module-docs:{key} -->\n"


class SyncDocVersionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs/sdk-baseline.json").write_text(
            '{"sdk_source_tag":"v5.0.0-ea3"}'
        )
        (self.root / "README.md").write_text(marked("sdk-source"))
        (self.root / "DEVELOPER.md").write_text("CUDA 13.x; Camera 0.6.0\n")
        (self.root / "RELEASE_NOTES.md").write_text("History: SDK v5.0.0-ea2\n")
        (self.root / "holoscan_camera").write_text(
            'export HOLOSCAN_CLI_BASE_IMAGE="${HOLOSCAN_CLI_BASE_IMAGE:-example.com/sdk:5.0}"\n'
        )

    def test_check_is_read_only_write_is_idempotent(self):
        before = (self.root / "README.md").read_bytes()
        self.assertEqual(synchronize(self.root), ["README.md"])
        self.assertEqual((self.root / "README.md").read_bytes(), before)
        synchronize(self.root, True)
        self.assertEqual(synchronize(self.root, True), [])
        self.assertIn("/releases/tag/v5.0.0-ea3", (self.root / "README.md").read_text())

    def test_input_only_change_updates_all_marked_occurrences(self):
        (self.root / "DEVELOPER.md").write_text(marked("sdk-source"))
        synchronize(self.root, True)
        (self.root / "docs/sdk-baseline.json").write_text(
            '{"sdk_source_tag":"v5.0.0-ea4"}'
        )
        self.assertEqual(synchronize(self.root), ["README.md", "DEVELOPER.md"])
        synchronize(self.root, True)
        for name in ("README.md", "DEVELOPER.md"):
            self.assertIn("EA4", (self.root / name).read_text())
            self.assertNotIn("EA3", (self.root / name).read_text())

    def test_preserves_history_unmarked_versions_and_runtime(self):
        original = {
            p.name: p.read_bytes()
            for p in self.root.iterdir()
            if p.is_file() and p.name != "README.md"
        }
        synchronize(self.root, True)
        for name, data in original.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_rejects_malformed_nested_unknown_and_unclosed_markers(self):
        for text in [
            marked("unknown"),
            "<!-- module-docs:sdk-source -->\n",
            "<!-- /module-docs:sdk-source -->\n",
            "<!-- module-docs:sdk-source -->\n" + marked("sdk-source"),
            "prefix <!-- module-docs:sdk-source -->\n",
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                rewrite(self.root, text)

    def test_validation_precedes_any_writes(self):
        before = (self.root / "README.md").read_bytes()
        (self.root / "DEVELOPER.md").write_text(marked("unknown"))
        with self.assertRaises(ValueError):
            synchronize(self.root, True)
        self.assertEqual((self.root / "README.md").read_bytes(), before)

    def test_internal_image_and_wrapper_default_remain_independent(self):
        path = self.root / "internal/docs"
        path.mkdir(parents=True)
        (path / "sdk-development.json").write_text(
            '{"sdk_development_image":"example.com/sdk:main"}'
        )
        (path / "development.md").write_text(
            marked("sdk-development-image") + marked("sdk-default-image")
        )
        synchronize(self.root, True)
        self.assertIn("example.com/sdk:main", (path / "development.md").read_text())
        self.assertIn("example.com/sdk:5.0", (path / "development.md").read_text())
        (self.root / "docs/sdk-baseline.json").write_text(
            '{"sdk_source_tag":"v5.0.0-rc6"}'
        )
        self.assertEqual(synchronize(self.root), ["README.md"])

    def test_public_tree_requires_no_internal_configuration(self):
        synchronize(self.root, True)
        self.assertFalse((self.root / "internal").exists())
        self.assertEqual(synchronize(self.root), [])

    def test_rejects_malformed_source_identity(self):
        for value in ["main", "5.0", "v5.0.0-ea3/other", 123]:
            (self.root / "docs/sdk-baseline.json").write_text(
                json.dumps({"sdk_source_tag": value})
            )
            with self.subTest(value=value), self.assertRaises(ValueError):
                render(self.root, "sdk-source")

    def test_planned_ga_image_stays_separate_from_ea_source(self):
        config = self.root / "docs/ga-container.json"
        config.write_text(
            json.dumps(
                {
                    "planned_sdk_image": "nvcr.io/nvidia/clara-holoscan/holoscan:v5.0.0-cuda13"
                }
            )
        )
        (self.root / "DEVELOPER.md").write_text(marked("sdk-ga-image"))
        synchronize(self.root, True)
        self.assertIn(
            "nvcr.io/nvidia/clara-holoscan/holoscan:v5.0.0-cuda13",
            (self.root / "DEVELOPER.md").read_text(),
        )
        (self.root / "docs/sdk-baseline.json").write_text(
            '{"sdk_source_tag":"v5.0.0-ea4"}'
        )
        self.assertEqual(synchronize(self.root), ["README.md"])
        config.write_text('{"planned_sdk_image":"example.com/unreviewed:latest"}')
        with self.assertRaises(ValueError):
            synchronize(self.root)

    def test_missing_or_ambiguous_wrapper_default_fails(self):
        for value in ["", (self.root / "holoscan_camera").read_text() * 2]:
            (self.root / "holoscan_camera").write_text(value)
            with self.assertRaises(ValueError):
                render(self.root, "sdk-default-image")


if __name__ == "__main__":
    unittest.main()
