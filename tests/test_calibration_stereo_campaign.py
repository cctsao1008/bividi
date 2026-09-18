from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bividi.calibration import stereo_campaign


class StereoCampaignModuleTests(unittest.TestCase):
    def _args(self, *, session_count: int = 2) -> argparse.Namespace:
        return argparse.Namespace(
            campaign_id="fixture-campaign",
            model="fixture-model",
            serial="fixture-serial",
            device=0,
            mode=1,
            pixel_format="GRAY8",
            width=1920,
            height=1200,
            camera_mapping_evidence="#35 fixture mapping evidence",
            session_count=session_count,
            policy_source="fixture-policy",
        )

    def test_manifest_preserves_stage_graph_guardrails_and_legacy_provenance(self):
        manifest = stereo_campaign.manifest(self._args(session_count=2))
        self.assertEqual(manifest["schema"], stereo_campaign.SCHEMA)
        self.assertEqual(manifest["session_count"], 2)
        self.assertEqual(
            manifest["provenance"]["tool"],
            "plan_stereo_calibration_campaign.py",
        )
        stage_ids = [stage["id"] for stage in manifest["stages"]]
        self.assertEqual(stage_ids[:2], ["target_definition", "target_scale"])
        self.assertIn("session_01_capture", stage_ids)
        self.assertIn("session_02_geometry", stage_ids)
        self.assertEqual(stage_ids[-2:], ["repeatability", "promotion"])
        promotion = manifest["stages"][-1]
        self.assertEqual(promotion["depends_on"], ["repeatability"])
        self.assertTrue(
            any("No numeric acceptance threshold" in item for item in manifest["guardrails"])
        )

    def test_session_count_below_two_is_rejected(self):
        with self.assertRaises(stereo_campaign.CampaignError):
            stereo_campaign.build_stages(1)

    def test_runbook_preserves_execution_and_final_rules(self):
        manifest = stereo_campaign.manifest(self._args())
        text = stereo_campaign.runbook(manifest)
        self.assertIn("# Stereo Physical Calibration Campaign", text)
        self.assertIn("Target scale first; diverse captures second", text)
        self.assertIn("Optional AprilGrid/Kalibr cross-check", text)
        self.assertIn("Explicit thresholds must come from the recorded lab/product policy", text)

    def test_audit_tracks_dependency_progress_without_claiming_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "campaign.json"
            manifest = stereo_campaign.manifest(self._args())
            stereo_campaign.write(manifest_path, manifest)

            initial = stereo_campaign.audit(manifest_path)
            self.assertEqual(initial["schema"], stereo_campaign.AUDIT_SCHEMA)
            self.assertEqual(initial["summary"]["complete"], 0)
            self.assertEqual(initial["stages"][0]["state"], "ready")
            self.assertEqual(initial["stages"][1]["state"], "blocked")
            self.assertIn("Presence/schema audit only", initial["note"])

            target_output = root / manifest["stages"][0]["outputs"][0]["path"]
            target_output.parent.mkdir(parents=True, exist_ok=True)
            target_output.write_text(
                json.dumps({"schema": "bividi.calibration.stereo_target.v1"}),
                encoding="utf-8",
            )
            progressed = stereo_campaign.audit(manifest_path)
            self.assertEqual(progressed["stages"][0]["state"], "complete")
            self.assertEqual(progressed["stages"][1]["state"], "ready")
            self.assertFalse(progressed["promotion_artifact_present"])

    def test_init_cli_creates_manifest_and_runbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "campaign"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = stereo_campaign.entrypoint(
                    [
                        "init",
                        str(root),
                        "--campaign-id",
                        "fixture",
                        "--model",
                        "model",
                        "--serial",
                        "serial",
                        "--device",
                        "0",
                        "--mode",
                        "1",
                        "--pixel-format",
                        "GRAY8",
                        "--width",
                        "1920",
                        "--height",
                        "1200",
                        "--camera-mapping-evidence",
                        "#35 fixture",
                        "--session-count",
                        "2",
                        "--policy-source",
                        "fixture-policy",
                    ]
                )
            self.assertEqual(rc, 0)
            manifest_path = root / "campaign.json"
            runbook_path = root / "RUNBOOK.md"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], stereo_campaign.SCHEMA)
            self.assertEqual(
                manifest["provenance"]["tool"],
                "plan_stereo_calibration_campaign.py",
            )
            self.assertIn(
                "Stereo Physical Calibration Campaign",
                runbook_path.read_text(encoding="utf-8"),
            )
            # Windows may print the long path while tempfile exposes an 8.3 alias.
            # The user-visible contract is that both created artifact names are reported.
            output = stdout.getvalue()
            self.assertIn("campaign.json", output)
            self.assertIn("RUNBOOK.md", output)

    def test_nonempty_campaign_root_preserves_exit_code_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "campaign"
            root.mkdir()
            (root / "existing.txt").write_text("evidence", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = stereo_campaign.entrypoint(
                    [
                        "init",
                        str(root),
                        "--campaign-id",
                        "fixture",
                        "--model",
                        "model",
                        "--serial",
                        "serial",
                        "--device",
                        "0",
                        "--mode",
                        "1",
                        "--pixel-format",
                        "GRAY8",
                        "--width",
                        "1920",
                        "--height",
                        "1200",
                        "--session-count",
                        "2",
                    ]
                )
            self.assertEqual(rc, 2)
            self.assertIn("campaign root is not empty", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
