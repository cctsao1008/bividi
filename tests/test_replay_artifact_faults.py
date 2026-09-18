from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bividi.replay_artifact_faults import (
    APPLICATION_SCHEMA,
    ReplayArtifactFaultError,
    SCHEMA,
    apply_recipe,
    recipe_sha256,
    tree_digest,
    validate_recipe,
)


def fixture_tree(root: Path) -> None:
    (root / "camera_a").mkdir(parents=True)
    (root / "capture.json").write_text(
        json.dumps(
            {
                "schema": "bividi.nori.camera_imu_dynamic_trace.v1",
                "device": {"serial": "SYN-001"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "frames.csv").write_text(
        "frame_index,frame_sequence\n0,10\n1,11\n",
        encoding="utf-8",
    )
    (root / "camera_a" / "0000000000.png").write_bytes(bytes(range(32)))


class ReplayArtifactFaultRecipeTests(unittest.TestCase):
    def test_apply_recipe_is_copy_on_write_and_hash_bound(self):
        recipe = {
            "schema": SCHEMA,
            "seed": "18446744073709551615",
            "rules": [
                {
                    "id": "manifest-schema",
                    "target": "capture.json",
                    "action": "replace_text",
                    "old": "bividi.nori.camera_imu_dynamic_trace.v1",
                    "new": "bividi.corrupt.v1",
                    "expected_disposition": "schema_reject",
                },
                {
                    "id": "truncate-image",
                    "target": "camera_a/0000000000.png",
                    "action": "truncate_file",
                    "size_bytes": 7,
                    "expected_disposition": "decode_failure",
                },
                {
                    "id": "csv-byte",
                    "target": "frames.csv",
                    "action": "xor_byte",
                    "offset": 0,
                    "mask": 1,
                    "expected_disposition": "reject_artifact",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            output = Path(tmp) / "mutated"
            source.mkdir()
            fixture_tree(source)
            source_digest = tree_digest(source)
            manifest = apply_recipe(source, output, recipe)

            self.assertEqual(manifest["schema"], APPLICATION_SCHEMA)
            self.assertEqual(manifest["seed"], (1 << 64) - 1)
            self.assertEqual(manifest["source_tree_sha256"], source_digest)
            self.assertTrue(manifest["source_unchanged_after_copy"])
            self.assertEqual(tree_digest(source), source_digest)
            self.assertNotEqual(manifest["output_tree_sha256"], source_digest)
            self.assertEqual(manifest["recipe_sha256"], recipe_sha256(recipe))
            self.assertEqual(len(manifest["rules_applied"]), 3)
            self.assertIn("bividi.corrupt.v1", (output / "capture.json").read_text(encoding="utf-8"))
            self.assertEqual((output / "camera_a" / "0000000000.png").stat().st_size, 7)
            self.assertEqual((source / "camera_a" / "0000000000.png").stat().st_size, 32)

    def test_replace_bytes_hex_supports_deterministic_wrong_media_fixture(self):
        recipe = {
            "schema": SCHEMA,
            "seed": 0,
            "rules": [
                {
                    "id": "replace-image",
                    "target": "camera_a/0000000000.png",
                    "action": "replace_bytes_hex",
                    "data_hex": "50350a3220310a3235350a0102",
                    "expected_disposition": "decode_failure",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            output = Path(tmp) / "mutated"
            source.mkdir()
            fixture_tree(source)
            apply_recipe(source, output, recipe)
            self.assertEqual(
                (output / "camera_a" / "0000000000.png").read_bytes(),
                bytes.fromhex("50350a3220310a3235350a0102"),
            )

    def test_delete_file_is_explicit(self):
        recipe = {
            "schema": SCHEMA,
            "seed": 1,
            "rules": [
                {
                    "id": "missing-csv",
                    "target": "frames.csv",
                    "action": "delete_file",
                    "expected_disposition": "reject_artifact",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            output = Path(tmp) / "mutated"
            source.mkdir()
            fixture_tree(source)
            manifest = apply_recipe(source, output, recipe)
            self.assertFalse((output / "frames.csv").exists())
            self.assertIsNone(manifest["rules_applied"][0]["after_sha256"])

    def test_recipe_rejects_escape_duplicate_ids_and_unknown_fields(self):
        base = {
            "schema": SCHEMA,
            "seed": 0,
            "rules": [
                {
                    "id": "a",
                    "target": "frames.csv",
                    "action": "truncate_file",
                    "size_bytes": 1,
                    "expected_disposition": "reject_artifact",
                }
            ],
        }
        bad = json.loads(json.dumps(base))
        bad["rules"][0]["target"] = "../outside"
        with self.assertRaisesRegex(ReplayArtifactFaultError, "normalized relative path"):
            validate_recipe(bad)

        bad = json.loads(json.dumps(base))
        bad["rules"].append(dict(bad["rules"][0]))
        with self.assertRaisesRegex(ReplayArtifactFaultError, "unique"):
            validate_recipe(bad)

        bad = json.loads(json.dumps(base))
        bad["rules"][0]["unexpected"] = True
        with self.assertRaisesRegex(ReplayArtifactFaultError, "unsupported keys"):
            validate_recipe(bad)

    def test_failed_rule_removes_partial_output(self):
        recipe = {
            "schema": SCHEMA,
            "seed": 0,
            "rules": [
                {
                    "id": "bad-offset",
                    "target": "frames.csv",
                    "action": "xor_byte",
                    "offset": 999999,
                    "mask": 1,
                    "expected_disposition": "reject_artifact",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            output = Path(tmp) / "mutated"
            source.mkdir()
            fixture_tree(source)
            with self.assertRaisesRegex(ReplayArtifactFaultError, "outside file size"):
                apply_recipe(source, output, recipe)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
