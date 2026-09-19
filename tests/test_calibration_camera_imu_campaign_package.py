from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bividi import calib_cli
from bividi.calibration import camera_imu_campaign_command
from bividi.calibration import contract
from bividi.calibration import plan_camera_imu_physical_campaign as campaign


class CameraImuCampaignPackageMigrationTests(unittest.TestCase):
    def test_cli_routes_without_source_checkout(self):
        invocation = calib_cli.build_invocation(
            "camera-imu",
            "campaign",
            ["--self-test"],
            source_root=Path("/definitely/not/a/bividi/checkout"),
        )
        self.assertEqual(
            invocation,
            [sys.executable, "-m", "bividi.calibration.camera_imu_campaign_command", "--self-test"],
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
                        "camera-imu",
                        "campaign",
                        "--self-test",
                    ]
                )
            finally:
                os.chdir(previous)
        self.assertEqual(rc, contract.EXIT_OK)

    def test_packaged_self_test_preserves_campaign_audit_boundary(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            campaign.self_test()
        self.assertIn(
            "Camera-IMU physical campaign planner self-test: PASS",
            stdout.getvalue(),
        )

    def test_legacy_wrapper_still_runs_direct_self_test(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "plan_camera_imu_physical_campaign.py"), "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "Camera-IMU physical campaign planner self-test: PASS",
            completed.stdout,
        )

    def test_schema_time_and_historical_provenance_identity_are_frozen(self):
        self.assertEqual(campaign.SCHEMA, "bividi.calibration.camera_imu_physical_campaign.v1")
        self.assertEqual(campaign.TOOL_VERSION, "1")
        self.assertEqual(Path(campaign.__file__).name, "plan_camera_imu_physical_campaign.py")
        self.assertEqual(
            campaign.PINNED_KALIBR_REVISION,
            "1f60227442d25e36365ef5f72cd80b9666d73467",
        )
        self.assertEqual(
            campaign.TIME_OFFSET_DEFINITION,
            "t_imu_s = t_camera_reference_s + offset_s",
        )
        self.assertEqual(
            campaign.CAMERA_TIME_REFERENCES,
            ("exposure_start", "exposure_midpoint", "exposure_end"),
        )

    def test_stage_graph_preserves_repeatability_and_external_runtime_boundaries(self):
        stages = campaign.build_stages(2)
        by_id = {item["id"]: item for item in stages}
        ids = [item["id"] for item in stages]
        self.assertEqual(len(stages), 32)
        self.assertLess(ids.index("imu_config_consistency"), ids.index("imu_promote"))
        self.assertEqual(by_id["dynamic_01_target_observations"]["runtime"], "external_kalibr")
        self.assertEqual(by_id["dynamic_01_solve"]["runtime"], "external_kalibr")
        self.assertEqual(
            by_id["repeatability"]["depends_on"],
            ["dynamic_01_import", "dynamic_02_import"],
        )
        self.assertEqual(by_id["final_promotion"]["depends_on"], ["repeatability"])
        with self.assertRaises(campaign.CampaignError):
            campaign.build_stages(1)

    def test_init_and_incomplete_audit_are_successful_orchestration_not_quality_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "campaign"
            rc = camera_imu_campaign_command.entrypoint(
                [
                    "init",
                    str(root),
                    "--campaign-id",
                    "pkg-campaign",
                    "--model",
                    "SYNTHETIC",
                    "--serial",
                    "SYN-001",
                    "--device",
                    "0",
                    "--mode",
                    "1",
                    "--camera-time-reference",
                    "exposure_midpoint",
                    "--dynamic-session-count",
                    "2",
                    "--policy-source",
                    "lab policy CAMIMU-001",
                ]
            )
            self.assertEqual(rc, contract.EXIT_OK)
            manifest_path = root / "campaign.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], campaign.SCHEMA)
            self.assertEqual(
                manifest["provenance"],
                {"tool": "plan_camera_imu_physical_campaign.py", "tool_version": "1"},
            )
            self.assertEqual(manifest["dynamic_session_count"], 2)
            self.assertEqual(manifest["dependencies"]["camera_imu_issue"], 47)
            self.assertEqual(
                manifest["dependencies"]["kalibr_revision"],
                campaign.PINNED_KALIBR_REVISION,
            )
            self.assertTrue((root / "RUNBOOK.md").is_file())

            report = campaign.audit(manifest_path)
            self.assertEqual(
                report["schema"],
                "bividi.calibration.camera_imu_physical_campaign_audit.v1",
            )
            self.assertEqual(report["summary"]["complete"], 0)
            self.assertGreaterEqual(report["summary"]["ready"], 1)
            self.assertFalse(report["promotion_artifact_present"])
            self.assertIn("presence/schema audit only", report["note"].lower())
            self.assertEqual(
                camera_imu_campaign_command.entrypoint(["audit", str(manifest_path)]),
                contract.EXIT_OK,
            )

    def test_presence_schema_audit_does_not_infer_dependency_or_promotion_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = campaign.argparse.Namespace(
                campaign_id="audit-boundary",
                model="SYNTHETIC",
                serial="SYN-002",
                device=0,
                mode=0,
                camera_time_reference="exposure_midpoint",
                dynamic_session_count=2,
                policy_source=None,
            )
            manifest = campaign.make_manifest(args, root)
            manifest_path = root / "campaign.json"
            campaign.write_json(manifest_path, manifest)

            final_path = root / "final" / "camera-imu-evidence.json"
            campaign.write_json(
                final_path,
                {"schema": "bividi.calibration.camera_imu_evidence_manifest.v1"},
            )

            report = campaign.audit(manifest_path)
            final_stage = next(item for item in report["stages"] if item["id"] == "final_promotion")
            repeat_stage = next(item for item in report["stages"] if item["id"] == "repeatability")
            self.assertEqual(repeat_stage["state"], "blocked")
            self.assertEqual(final_stage["state"], "complete")
            self.assertTrue(report["promotion_artifact_present"])
            self.assertIn("does not replace", report["note"].lower())

    def test_domain_and_write_failures_map_to_two_and_never_three(self):
        self.assertEqual(
            camera_imu_campaign_command.entrypoint(
                [
                    "init",
                    "/tmp/unused-campaign",
                    "--campaign-id",
                    "bad",
                    "--model",
                    "SYNTHETIC",
                    "--serial",
                    "SYN",
                    "--device",
                    "0",
                    "--mode",
                    "0",
                    "--camera-time-reference",
                    "exposure_start",
                    "--dynamic-session-count",
                    "1",
                ]
            ),
            contract.EXIT_USAGE_OR_DOMAIN_ERROR,
        )
        self.assertEqual(
            camera_imu_campaign_command.entrypoint(
                ["audit", "/definitely/missing/campaign.json"]
            ),
            contract.EXIT_USAGE_OR_DOMAIN_ERROR,
        )
        with mock.patch.object(campaign, "main", return_value=3):
            self.assertEqual(
                camera_imu_campaign_command.entrypoint(["unused"]),
                contract.EXIT_USAGE_OR_DOMAIN_ERROR,
            )

    def test_nonempty_campaign_root_is_domain_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "campaign"
            root.mkdir()
            (root / "existing.txt").write_text("occupied\n", encoding="utf-8")
            rc = camera_imu_campaign_command.entrypoint(
                [
                    "init",
                    str(root),
                    "--campaign-id",
                    "occupied",
                    "--model",
                    "SYNTHETIC",
                    "--serial",
                    "SYN",
                    "--device",
                    "0",
                    "--mode",
                    "0",
                    "--camera-time-reference",
                    "exposure_end",
                    "--dynamic-session-count",
                    "2",
                ]
            )
        self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)

    def test_contract_metadata_records_orchestration_boundary(self):
        item = contract.contract_for("camera-imu", "campaign")
        self.assertEqual(item.module, "bividi.calibration.camera_imu_campaign_command")
        self.assertEqual(item.compatibility_tool, "plan_camera_imu_physical_campaign.py")
        self.assertEqual(item.output_role, "orchestration-json-markdown")
        self.assertEqual(item.policy_role, "recorded-orchestration-metadata")
        self.assertTrue(item.emits_versioned_provenance)
        self.assertEqual(item.tool_version, "1")
        self.assertIsNone(item.evaluated_fail_exit)


if __name__ == "__main__":
    unittest.main()
