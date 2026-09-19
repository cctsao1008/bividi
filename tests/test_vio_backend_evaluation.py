from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from bividi import vio_backend_evaluation as review


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "vio" / "backend-evaluation-v1.json"


class VioBackendEvaluationTests(unittest.TestCase):
    def test_repository_artifact_is_valid_and_not_adopted(self):
        document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(review.validate(document), [])
        self.assertEqual(document["decision"]["adoption_status"], "NOT_ADOPTED")
        self.assertIsNone(document["decision"]["selected_backend"])
        self.assertEqual(document["decision"]["spike_candidate"], "kimera-vio")

    def test_all_sources_are_pinned_and_windows_state_is_explicit(self):
        document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        for candidate in document["candidates"]:
            with self.subTest(candidate=candidate["id"]):
                self.assertRegex(candidate["revision"], r"^[0-9a-f]{40}$")
                self.assertIn(candidate["build"]["windows"]["status"], review.WINDOWS_STATES)
                self.assertTrue(candidate["evidence"])
                for source in candidate["evidence"]:
                    self.assertIn(candidate["revision"], source["url"])

    def test_copyleft_candidates_are_reference_only_without_project_decision(self):
        document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(document["project_license_context"]["copyleft_integration_decision"], "not_made")
        for candidate in document["candidates"]:
            if candidate["license"]["class"] == "strong-copyleft":
                self.assertEqual(candidate["disposition"], "reference_only")

    def test_premature_adoption_is_rejected(self):
        document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        document["decision"]["adoption_status"] = "ADOPTED"
        document["decision"]["selected_backend"] = "kimera-vio"
        errors = review.validate(document)
        self.assertTrue(any("all adoption gates PASS" in item for item in errors), errors)

    def test_unpinned_and_implicit_windows_claims_are_rejected(self):
        document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        bad = copy.deepcopy(document)
        bad["candidates"][0]["revision"] = "master"
        self.assertTrue(any("40-hex" in item for item in review.validate(bad)))
        bad = copy.deepcopy(document)
        bad["candidates"][0]["build"]["windows"]["status"] = "assumed"
        self.assertTrue(any("windows.status" in item for item in review.validate(bad)))

    def test_wrapper_self_test_and_artifact_validation(self):
        tool = ROOT / "tools" / "validate_vio_backend_evaluation.py"
        self_test = subprocess.run(
            [sys.executable, str(tool), "--self-test"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(self_test.returncode, 0, self_test.stdout + self_test.stderr)
        self.assertIn("self-test: PASS", self_test.stdout)
        validation = subprocess.run(
            [sys.executable, str(tool), str(ARTIFACT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        self.assertIn("NOT_ADOPTED", validation.stdout)


if __name__ == "__main__":
    unittest.main()
