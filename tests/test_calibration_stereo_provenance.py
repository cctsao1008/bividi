from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bividi.calibration import stereo_provenance


class StereoProvenanceModuleTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        profile: str = "promotion",
        manifest_policy: str | None = "lab-v1",
        quality_status: str = "PASS",
    ) -> tuple[argparse.Namespace, dict[str, Path]]:
        target_path = root / "target.json"
        target_path.write_text(
            json.dumps({"schema": stereo_provenance.TARGET_SCHEMA, "target_id": "t"}),
            encoding="utf-8",
        )
        target_hash = stereo_provenance.sha(target_path)

        capture_path = root / "capture.json"
        frames_path = root / "frames.csv"
        camera_a_path = root / "a.png"
        camera_b_path = root / "b.png"
        capture_path.write_text("{}", encoding="utf-8")
        frames_path.write_text("frame_index\n0\n", encoding="utf-8")
        camera_a_path.write_bytes(b"a")
        camera_b_path.write_bytes(b"b")

        session = {
            "schema": stereo_provenance.SESSION_SCHEMA,
            "session_id": "s",
            "provenance": {"kind": "measured"},
            "device": {"model": "M", "serial": "S"},
            "capture": {
                "mode_index": 0,
                "pixel_format": "GRAY8",
                "width": 640,
                "height": 480,
                "camera_mapping_evidence": "#35 physical mapping note",
            },
            "target": {"sha256": target_hash},
            "source_trace": {
                "kind": "test-recorder",
                "artifacts": [
                    {
                        "role": "capture_manifest",
                        "path": "capture.json",
                        "sha256": stereo_provenance.sha(capture_path),
                    },
                    {
                        "role": "frames_csv",
                        "path": "frames.csv",
                        "sha256": stereo_provenance.sha(frames_path),
                    },
                ],
            },
            "pairs": [
                {
                    "pair_id": "p0",
                    "camera_a": "a.png",
                    "camera_b": "b.png",
                    "camera_a_sha256": stereo_provenance.sha(camera_a_path),
                    "camera_b_sha256": stereo_provenance.sha(camera_b_path),
                }
            ],
        }
        session_path = root / "session.json"
        session_path.write_text(json.dumps(session), encoding="utf-8")
        session_hash = stereo_provenance.sha(session_path)

        gate = {"g": {"pass": quality_status == "PASS"}}
        target_scale = {
            "schema": stereo_provenance.TARGET_SCALE_SCHEMA,
            "target": {"sha256": target_hash},
            "status": quality_status,
            "gates": gate,
            "policy_source": "lab-v1",
        }
        dataset_quality = {
            "schema": stereo_provenance.QUALITY_SCHEMA,
            "session": {"sha256": session_hash},
            "target": {"sha256": target_hash},
            "status": quality_status,
            "gates": gate,
            "policy_source": "lab-v1",
        }
        calibration = {
            "schema": stereo_provenance.CALIB_SCHEMA,
            "calibration_id": "c",
            "provenance": {
                "kind": "measured",
                "source_session_sha256": session_hash,
            },
            "device": session["device"],
            "capture": session["capture"],
            "target": {"sha256": target_hash},
            "quality": {
                "status": quality_status,
                "gates": gate,
                "policy_source": "lab-v1",
            },
        }
        calibration_path = root / "calibration.json"
        calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
        calibration_hash = stereo_provenance.sha(calibration_path)

        geometry = {
            "schema": stereo_provenance.GEOMETRY_SCHEMA,
            "calibration": {"sha256": calibration_hash},
            "status": quality_status,
            "gates": gate,
            "policy_source": "lab-v1",
        }
        repeatability = {
            "schema": stereo_provenance.REPEAT_SCHEMA,
            "artifacts": [{"sha256": calibration_hash}],
            "status": quality_status,
            "gates": gate,
            "policy_source": "lab-v1",
        }

        files = {
            "target": target_path,
            "session": session_path,
            "calibration": calibration_path,
        }
        for role, document in (
            ("target_scale", target_scale),
            ("dataset_quality", dataset_quality),
            ("geometry_review", geometry),
            ("repeatability", repeatability),
        ):
            path = root / f"{role}.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            files[role] = path

        output = root / "manifest.json"
        args = argparse.Namespace(
            output=output,
            profile=profile,
            policy_source=manifest_policy,
            **files,
        )
        files["camera_a"] = camera_a_path
        return args, files

    def test_promotion_ready_preserves_manifest_schema_and_legacy_tool_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, _ = self._fixture(Path(tmp))
            manifest = stereo_provenance.build(args)
            self.assertEqual(manifest["schema"], stereo_provenance.MANIFEST_SCHEMA)
            self.assertEqual(manifest["disposition"], "PROMOTION_READY")
            self.assertEqual(manifest["findings"], [])
            self.assertEqual(
                manifest["provenance"],
                {"tool": "stereo_calibration_provenance.py", "tool_version": "1"},
            )

    def test_missing_manifest_policy_blocks_promotion_without_inventing_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, _ = self._fixture(Path(tmp), manifest_policy=None)
            manifest = stereo_provenance.build(args)
            self.assertEqual(manifest["disposition"], "FAIL")
            self.assertIn(
                "promotion requires non-placeholder manifest policy_source",
                manifest["findings"],
            )

    def test_integrity_and_review_profiles_preserve_distinct_status_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            integrity_args, _ = self._fixture(
                root / "integrity",
                profile="integrity",
                quality_status="FAIL",
            )
            integrity_args.output.parent.mkdir(parents=True, exist_ok=True)
            integrity = stereo_provenance.build(integrity_args)
            self.assertEqual(integrity["disposition"], "INTEGRITY_OK")

            review_args, _ = self._fixture(
                root / "review",
                profile="review",
                quality_status="FAIL",
            )
            review_args.output.parent.mkdir(parents=True, exist_ok=True)
            review = stereo_provenance.build(review_args)
            self.assertEqual(review["disposition"], "FAIL")
            self.assertTrue(any("status is FAIL" in item for item in review["findings"]))

    def test_verify_detects_mutated_bound_camera_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, files = self._fixture(Path(tmp))
            manifest = stereo_provenance.build(args)
            args.output.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                stereo_provenance.verify(args.output)["disposition"],
                "PROMOTION_READY",
            )
            files["camera_a"].write_bytes(b"changed")
            verified = stereo_provenance.verify(args.output)
            self.assertEqual(verified["disposition"], "FAIL")
            self.assertTrue(any("camera_a SHA-256 mismatch" in item for item in verified["findings"]))

    def test_build_cli_preserves_fail_exit_code_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, files = self._fixture(Path(tmp), manifest_policy=None)
            argv = ["build"]
            for role in stereo_provenance.ROLES:
                argv.extend(["--" + role.replace("_", "-"), str(files[role])])
            argv.extend(
                [
                    "--profile",
                    "promotion",
                    "--output",
                    str(args.output),
                ]
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = stereo_provenance.entrypoint(argv)
            self.assertEqual(rc, 3)
            self.assertIn("FAIL", stdout.getvalue())
            self.assertTrue(args.output.is_file())

    def test_domain_error_preserves_exit_code_two(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = stereo_provenance.entrypoint([])
        self.assertEqual(rc, 2)
        self.assertIn("choose build/verify or --self-test", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
