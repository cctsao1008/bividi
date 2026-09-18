from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import contract, imu_provenance as impl, imu_provenance_command as command


class ImuProvenancePackageMigrationTests(unittest.TestCase):
    def _basic_manifest(self, root: Path, *, kind: str = "synthetic") -> tuple[Path, dict]:
        summary = impl.write_fake_capture(root, "capture")
        manifest_path = root / "manifest.json"
        args = argparse.Namespace(
            output=manifest_path,
            capture=[f"stationary={summary}"],
            analysis=[],
            session_id="synthetic-package-provenance",
            device_model="DECXIN AR0234 synthetic fixture",
            imu_model="ICM-42688-P",
            imu_frame="bividi_imu",
            accel_range_g=4.0,
            gyro_range_dps=1000.0,
            odr_hz=200.0,
            accel_filter="synthetic-filter-A",
            gyro_filter="synthetic-filter-G",
            configuration_source="synthetic package fixture",
            note=[],
            kind=kind,
        )
        manifest = impl.create_manifest(args)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path, manifest

    def test_cli_routes_installed_command_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "imu",
            "provenance",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.imu_provenance_command", "--self-test"],
        )

    def test_cli_executes_self_test_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "imu",
                        "provenance",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_characterized_self_test_is_preserved(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = impl.self_test()
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertIn("IMU calibration provenance gate self-test: PASS", stdout.getvalue())

    def test_manifest_preserves_historical_provenance_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, manifest = self._basic_manifest(Path(tmp))
            self.assertEqual(manifest["schema"], impl.MANIFEST_SCHEMA)
            self.assertEqual(manifest["provenance"]["tool"], "tools/imu_calibration_provenance.py")
            self.assertEqual(manifest["provenance"]["tool_version"], "1")

    def test_structural_promotion_role_set_is_not_silently_expanded(self):
        self.assertEqual(
            impl.FULL_ANALYSIS_ROLES,
            {"stationary", "allan", "six_position", "gyro_rotation"},
        )
        self.assertNotIn("config_consistency", impl.FULL_ANALYSIS_ROLES)
        self.assertNotIn("config_consistency", impl.EXPECTED_ANALYSIS_SCHEMAS)

    def test_completed_gate_fail_uses_exit_three_but_domain_error_uses_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._basic_manifest(root)
            trace_path = impl.resolve_manifest_path(manifest["captures"][0]["trace_path"], manifest_path, None)
            trace_path.write_text(trace_path.read_text(encoding="utf-8") + "true,1010000,0,0,8192,1,-2,3\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = command.entrypoint(["verify", str(manifest_path)])
            self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = command.entrypoint(["verify", "/definitely/missing/manifest.json"])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertIn("cannot read JSON", stderr.getvalue())

    def test_contract_metadata_records_structural_not_numerical_promotion(self):
        item = contract.contract_for("imu", "provenance")
        self.assertEqual(item.module, "bividi.calibration.imu_provenance_command")
        self.assertEqual(item.compatibility_tool, "imu_calibration_provenance.py")
        self.assertEqual(item.output_role, "machine-evidence-json")
        self.assertEqual(item.policy_role, "structural-provenance-gate-no-numerical-policy")
        self.assertTrue(item.emits_versioned_provenance)
        self.assertEqual(item.tool_version, "1")
        self.assertEqual(item.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)


if __name__ == "__main__":
    unittest.main()
