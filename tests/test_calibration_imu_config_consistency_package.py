from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from bividi import calib_cli
from bividi.calibration import contract, imu_config_consistency as impl, imu_config_consistency_command as command


class ImuConfigConsistencyPackageMigrationTests(unittest.TestCase):
    def _fixture(self, root: Path, *, declared_odr_hz: float = 200.0) -> tuple[Path, Path]:
        accel_range = 4.0
        actual_odr = 200.0
        expected_accel = impl.SIGNED_RAW_FULL_SCALE_COUNTS / accel_range
        sixpos = {
            "schema": impl.SIXPOS_SCHEMA,
            "accelerometer_axis_mapping": {
                "counts_per_g_column_l2": {axis: expected_accel for axis in impl.AXES}
            },
            "poses": {
                pose: {"timing": {"effective_rate_hz": actual_odr}}
                for pose in ("plus_x", "minus_x", "plus_y", "minus_y", "plus_z", "minus_z")
            },
        }
        sixpos_path = root / "sixpos.json"
        impl.write_json(sixpos_path, sixpos)
        manifest_path = root / "manifest.json"
        impl.write_json(
            manifest_path,
            {
                "schema": impl.MANIFEST_SCHEMA,
                "session_id": "synthetic-package-config-consistency",
                "imu_configuration": {
                    "model": "synthetic-imu",
                    "frame": "imu",
                    "accelerometer_range_g": accel_range,
                    "gyroscope_range_dps": 1000.0,
                    "output_data_rate_hz": declared_odr_hz,
                    "accelerometer_filter": "declared-only",
                    "gyroscope_filter": "declared-only",
                    "configuration_source": "synthetic fixture",
                },
                "analysis": [
                    {
                        "role": "six_position",
                        "path": sixpos_path.name,
                        "sha256": impl.sha256_file(sixpos_path),
                        "bytes": sixpos_path.stat().st_size,
                        "schema": impl.SIXPOS_SCHEMA,
                    }
                ],
            },
        )
        return manifest_path, sixpos_path

    def test_cli_routes_installed_command_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "imu",
            "config-consistency",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.imu_config_consistency_command", "--self-test"],
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
                        "config-consistency",
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
        self.assertIn("IMU configuration consistency laboratory self-test: PASS", stdout.getvalue())

    def test_evidence_only_report_and_filter_boundary_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _ = self._fixture(root)
            json_out = root / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = command.entrypoint([str(manifest_path), "--json-out", str(json_out)])
            self.assertEqual(rc, contract.EXIT_OK)
            report = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], impl.REPORT_SCHEMA)
            self.assertEqual(report["status"], "EVIDENCE_ONLY_NO_THRESHOLDS")
            self.assertFalse(report["filter_configuration"]["physically_verified"])
            self.assertIn("not sensor-register readback", " ".join(report["guardrails"]))

    def test_explicit_gate_fail_uses_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _ = self._fixture(root, declared_odr_hz=100.0)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = command.entrypoint(
                    [str(manifest_path), "--max-odr-error-pct", "5"]
                )
            self.assertEqual(rc, contract.EXIT_EVALUATED_FAIL)

    def test_domain_error_and_hash_mutation_use_exit_two(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = command.entrypoint([])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, sixpos_path = self._fixture(root)
            sixpos_path.write_text("{}\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = command.entrypoint([str(manifest_path)])
            self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
            self.assertIn("hash mismatch", stderr.getvalue())

    def test_contract_metadata_records_explicit_gate_semantics(self):
        item = contract.contract_for("imu", "config-consistency")
        self.assertEqual(item.module, "bividi.calibration.imu_config_consistency_command")
        self.assertEqual(item.compatibility_tool, "analyze_imu_config_consistency.py")
        self.assertEqual(item.output_role, "machine-evidence-json-and-human-markdown")
        self.assertEqual(item.policy_role, "explicit-operator-gates-no-default-thresholds")
        self.assertEqual(item.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)


if __name__ == "__main__":
    unittest.main()
