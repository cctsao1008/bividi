from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bividi.vio_kimera_external_probe import PINNED_REVISION, execute_probe


def run(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    ).stdout.strip()


def make_source(root: Path) -> tuple[Path, str]:
    source = root / "kimera-source"
    source.mkdir()
    run(["git", "init"], source)
    run(["git", "config", "user.email", "fixture@example.invalid"], source)
    run(["git", "config", "user.name", "Fixture"], source)
    (source / "README").write_text("fixture\n", encoding="utf-8")
    run(["git", "add", "README"], source)
    run(["git", "commit", "-m", "fixture"], source)
    return source, run(["git", "rev-parse", "HEAD"], source)


def make_package(root: Path, namespaced: bool) -> Path:
    prefix = root / ("pkg-ns" if namespaced else "pkg-plain")
    include = prefix / "include" / "kimera-vio"
    (include / "common").mkdir(parents=True, exist_ok=True)
    (include / "pipeline").mkdir(parents=True, exist_ok=True)
    (include / "common" / "vio_types.h").write_text(
        "#pragma once\n#include <cstdint>\nnamespace VIO { using Timestamp=std::int64_t; }\n",
        encoding="utf-8",
    )
    (include / "pipeline" / "Pipeline-definitions.h").write_text(
        textwrap.dedent(
            """\
            #pragma once
            #include <string>
            namespace VIO { struct VioParams { explicit VioParams(const std::string&) {} }; }
            """
        ),
        encoding="utf-8",
    )
    config = prefix / "lib" / "cmake" / "kimera_vio" / "kimera_vioConfig.cmake"
    config.parent.mkdir(parents=True, exist_ok=True)
    target = "kimera_vio::kimera_vio" if namespaced else "kimera_vio"
    config.write_text(
        f"add_library({target} INTERFACE IMPORTED)\n"
        f"set_target_properties({target} PROPERTIES INTERFACE_INCLUDE_DIRECTORIES \"{(prefix / 'include').as_posix()}\")\n",
        encoding="utf-8",
    )
    return prefix


class KimeraExternalProbeRunnerTest(unittest.TestCase):
    def test_synthetic_runner_revision_reject_and_dirty_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, head = make_source(root)

            for namespaced, expected_kind in ((True, "build-tree-alias"), (False, "installed-export")):
                prefix = make_package(root, namespaced)
                evidence = root / f"evidence-{expected_kind}.json"
                rc, document = execute_probe(
                    repo_root=ROOT,
                    kimera_source=source,
                    build_dir=root / f"build-{expected_kind}",
                    evidence_out=evidence,
                    cmake_prefix=prefix,
                    kimera_vio_dir=None,
                    timeout_s=60,
                    evidence_kind="synthetic",
                    expected_source_revision=head,
                    package_source_binding="synthetic_fixture",
                )
                self.assertEqual(rc, 0)
                self.assertEqual(document["status"], "PASS_SYNTHETIC_FIXTURE")
                self.assertFalse(document["source"]["matches_upstream_pin"])
                self.assertEqual(document["probe"]["reported_pinned_revision"], PINNED_REVISION)
                self.assertEqual(document["probe"]["resolved_target_kind"], expected_kind)
                self.assertEqual(document["package"]["source_binding"], "synthetic_fixture")
                self.assertFalse(document["package"]["source_binding_verified"])
                saved = json.loads(evidence.read_text(encoding="utf-8"))
                self.assertEqual(saved["status"], "PASS_SYNTHETIC_FIXTURE")
                self.assertIn("output_sha256", saved["steps"]["probe"])

            rejected = root / "rejected.json"
            rc, document = execute_probe(
                repo_root=ROOT,
                kimera_source=source,
                build_dir=root / "build-reject",
                evidence_out=rejected,
                cmake_prefix=make_package(root, True),
                kimera_vio_dir=None,
                timeout_s=60,
                evidence_kind="synthetic",
                expected_source_revision="0" * 40,
                package_source_binding="synthetic_fixture",
            )
            self.assertEqual(rc, 2)
            self.assertEqual(document["status"], "REJECTED_SOURCE_REVISION")
            self.assertFalse((root / "build-reject").exists())

            (source / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            dirty_evidence = root / "dirty.json"
            rc, document = execute_probe(
                repo_root=ROOT,
                kimera_source=source,
                build_dir=root / "build-dirty",
                evidence_out=dirty_evidence,
                cmake_prefix=make_package(root, False),
                kimera_vio_dir=None,
                timeout_s=60,
                evidence_kind="synthetic",
                expected_source_revision=head,
                package_source_binding="synthetic_fixture",
            )
            self.assertEqual(rc, 0)
            self.assertTrue(document["source"]["dirty"])


if __name__ == "__main__":
    unittest.main()
