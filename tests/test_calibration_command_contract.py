from __future__ import annotations

import contextlib
import importlib
import io
import unittest

from bividi import calib_cli
from bividi.calibration import contract


class CalibrationCommandContractTests(unittest.TestCase):
    def test_contract_keys_are_unique_and_match_package_native_cli_routes(self):
        keys = [item.key for item in contract.STEREO_COMMAND_CONTRACTS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(
            keys,
            [
                ("stereo", "target-scale"),
                ("stereo", "geometry-review"),
                ("stereo", "repeatability"),
                ("stereo", "promote"),
                ("stereo", "report"),
                ("stereo", "campaign"),
            ],
        )
        for item in contract.STEREO_COMMAND_CONTRACTS:
            with self.subTest(command=item.name):
                routed = calib_cli.resolve_command(item.group, item.name)
                self.assertIsNone(routed.script)
                self.assertEqual(routed.module, item.module)

    def test_exit_code_vocabulary_is_frozen(self):
        self.assertEqual(contract.EXIT_OK, 0)
        self.assertEqual(contract.EXIT_USAGE_OR_DOMAIN_ERROR, 2)
        self.assertEqual(contract.EXIT_EVALUATED_FAIL, 3)

        evaluated = {
            item.name: item.evaluated_fail_exit
            for item in contract.STEREO_COMMAND_CONTRACTS
        }
        self.assertEqual(evaluated["target-scale"], 3)
        self.assertEqual(evaluated["geometry-review"], 3)
        self.assertEqual(evaluated["repeatability"], 3)
        self.assertEqual(evaluated["promote"], 3)
        self.assertIsNone(evaluated["report"])
        self.assertIsNone(evaluated["campaign"])

    def test_all_frozen_modules_share_success_and_domain_error_basics(self):
        for item in contract.STEREO_COMMAND_CONTRACTS:
            module = importlib.import_module(item.module)
            with self.subTest(command=item.name, path="self-test"):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    rc = module.entrypoint(["--self-test"])
                self.assertEqual(rc, contract.EXIT_OK)

            with self.subTest(command=item.name, path="domain-error"):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    rc = module.entrypoint([])
                self.assertEqual(rc, contract.EXIT_USAGE_OR_DOMAIN_ERROR)
                self.assertIn("error:", stderr.getvalue())

    def test_versioned_artifact_producers_preserve_historical_tool_identity(self):
        for item in contract.STEREO_COMMAND_CONTRACTS:
            module = importlib.import_module(item.module)
            with self.subTest(command=item.name):
                if not item.emits_versioned_provenance:
                    self.assertIsNone(item.tool_version)
                    continue
                self.assertEqual(
                    getattr(module, "COMPATIBILITY_TOOL_NAME"),
                    item.compatibility_tool,
                )
                self.assertEqual(getattr(module, "TOOL_VERSION"), item.tool_version)

    def test_policy_and_output_roles_are_explicit_not_inferred(self):
        by_name = {item.name: item for item in contract.STEREO_COMMAND_CONTRACTS}
        self.assertEqual(
            by_name["target-scale"].policy_role,
            "named-source-required-for-explicit-gates",
        )
        self.assertEqual(
            by_name["geometry-review"].policy_role,
            "named-source-required-for-explicit-gates",
        )
        self.assertEqual(
            by_name["repeatability"].policy_role,
            "named-source-required-for-explicit-gates",
        )
        self.assertEqual(
            by_name["promote"].policy_role,
            "promotion-requires-manifest-and-evidence-policy",
        )
        self.assertEqual(by_name["report"].policy_role, "presentation-only")
        self.assertEqual(
            by_name["campaign"].policy_role,
            "recorded-orchestration-metadata",
        )

        self.assertEqual(by_name["report"].output_role, "human-report-markdown")
        self.assertEqual(
            by_name["campaign"].output_role,
            "orchestration-json-markdown",
        )
        for name in ("target-scale", "geometry-review", "repeatability", "promote"):
            self.assertEqual(by_name[name].output_role, "machine-evidence-json")

    def test_contract_lookup_is_explicit(self):
        item = contract.contract_for("stereo", "promote")
        self.assertEqual(item.module, "bividi.calibration.stereo_provenance")

        solve = contract.contract_for("stereo", "solve")
        self.assertEqual(solve.module, "bividi.calibration.stereo_workbench_command")
        self.assertEqual(solve.evaluated_fail_exit, contract.EXIT_EVALUATED_FAIL)

        with self.assertRaises(KeyError):
            contract.contract_for("stereo", "not-a-command")


if __name__ == "__main__":
    unittest.main()
