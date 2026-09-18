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
from bividi.calibration import (
    artifact_validator,
    contract,
    kalibr_imu_export,
    kalibr_imu_export_command,
)


class KalibrImuExportPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_installed_export_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "imu",
            "export-kalibr",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.kalibr_imu_export_command", "--self-test"],
        )

    def test_cli_executes_export_self_test_outside_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            os.chdir(tmp)
            try:
                rc = calib_cli.main(
                    [
                        "--source-root",
                        "/definitely/not/a/bividi/checkout",
                        "imu",
                        "export-kalibr",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_artifact_validator_preserves_characterized_self_test(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = artifact_validator.self_test()
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertIn("calibration artifact validator self-test: PASS", stdout.getvalue())

    def test_packaged_exporter_preserves_characterized_self_test(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = kalibr_imu_export.self_test()
        self.assertEqual(rc, contract.EXIT_OK)
        self.assertIn("Kalibr IMU exporter self-test: PASS", stdout.getvalue())

    def test_export_outputs_mapping_and_source_hash_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_path = root / "imu.json"
            yaml_path = root / "imu.yaml"
            manifest_path = root / "imu.export.json"
            artifact_path.write_text(
                json.dumps(artifact_validator.synthetic_imu(), sort_keys=True) + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = kalibr_imu_export_command.entrypoint(
                    [
                        str(artifact_path),
                        "--allow-synthetic",
                        "--rostopic",
                        "/imu0",
                        "--output",
                        str(yaml_path),
                        "--manifest-out",
                        str(manifest_path),
                    ]
                )
            self.assertEqual(rc, contract.EXIT_OK)
            yaml_text = yaml_path.read_text(encoding="utf-8")
            self.assertIn("accelerometer_noise_density: 0.002", yaml_text)
            self.assertIn("gyroscope_noise_density: 0.0002", yaml_text)
            self.assertIn("update_rate: 599.8", yaml_text)
            self.assertIn("rostopic: /imu0", yaml_text)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], kalibr_imu_export.EXPORT_SCHEMA)
            self.assertEqual(manifest["update_rate_source"], "timing.effective_rate_hz")
            self.assertEqual(manifest["source_sha256"], kalibr_imu_export.source_hash(artifact_path))
            self.assertEqual(
                manifest["mapping"]["gyroscope_noise_density"],
                "noise.gyroscope_noise_density_rad_s_sqrt_hz",
            )

    def test_missing_or_invalid_export_input_uses_exit_two_not_three(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = kalibr_imu_export_command.entrypoint([])
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
        self.assertNotEqual(rc, contract.EXIT_EVALUATED_FAIL)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_path = root / "imu.json"
            artifact_path.write_text(
                json.dumps(artifact_validator.synthetic_imu()),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = kalibr_imu_export_command.entrypoint([str(artifact_path)])
            self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
            self.assertIn("synthetic", stderr.getvalue())

    def test_exporter_never_falls_back_to_nominal_update_rate(self):
        artifact = artifact_validator.synthetic_imu()
        artifact.pop("timing")
        artifact["imu"].pop("sample_rate_hz_measured")
        with self.assertRaisesRegex(ValueError, "nominal rate is not substituted"):
            kalibr_imu_export.build_export(artifact, "/imu0", allow_synthetic=True)

    def test_contract_metadata_records_interoperability_boundary(self):
        item = contract.contract_for("imu", "export-kalibr")
        self.assertEqual(item.module, "bividi.calibration.kalibr_imu_export_command")
        self.assertEqual(item.compatibility_tool, "export_kalibr_imu.py")
        self.assertEqual(item.output_role, "interop-yaml-and-machine-manifest")
        self.assertEqual(item.policy_role, "measured-fields-required-synthetic-opt-in")
        self.assertFalse(item.emits_versioned_provenance)
        self.assertIsNone(item.evaluated_fail_exit)


if __name__ == "__main__":
    unittest.main()
