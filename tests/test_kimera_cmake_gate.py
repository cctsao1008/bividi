from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

PIN = "ce8c59b7b273ab5ac29db7e5572e1623760e19c7"
ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _write_fake_package(root: Path, kind: str) -> Path:
    prefix = root / kind
    include = prefix / "include" / "kimera-vio"
    (include / "common").mkdir(parents=True)
    (include / "pipeline").mkdir(parents=True)
    (include / "common" / "vio_types.h").write_text(
        "#pragma once\n#include <cstdint>\nnamespace VIO { using Timestamp = std::int64_t; }\n",
        encoding="utf-8",
    )
    (include / "pipeline" / "Pipeline-definitions.h").write_text(
        textwrap.dedent(
            """\
            #pragma once
            #include <string>
            namespace VIO {
            struct VioParams {
              explicit VioParams(const std::string&) {}
            };
            }
            """
        ),
        encoding="utf-8",
    )
    config = prefix / "lib" / "cmake" / "kimera_vio" / "kimera_vioConfig.cmake"
    config.parent.mkdir(parents=True)
    target = "kimera_vio::kimera_vio" if kind == "namespaced" else "kimera_vio"
    config.write_text(
        f"add_library({target} INTERFACE IMPORTED)\n"
        f"set_target_properties({target} PROPERTIES INTERFACE_INCLUDE_DIRECTORIES \"{(prefix / 'include').as_posix()}\")\n",
        encoding="utf-8",
    )
    return prefix


def _write_bad_package(root: Path) -> Path:
    prefix = root / "bad"
    config = prefix / "lib" / "cmake" / "kimera_vio" / "kimera_vioConfig.cmake"
    config.parent.mkdir(parents=True)
    config.write_text("# deliberately exports neither expected target\n", encoding="utf-8")
    return prefix


class KimeraExternalCMakeGateTest(unittest.TestCase):
    def test_target_resolution_pin_and_link_probe(self) -> None:
        external_source = ROOT / "cmake" / "kimera-external"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = {
                "namespaced": _write_fake_package(root, "namespaced"),
                "plain": _write_fake_package(root, "plain"),
            }
            expected = {
                "namespaced": "build-tree-alias",
                "plain": "installed-export",
            }
            for name, prefix in fixtures.items():
                build = root / f"build-{name}"
                configured = _run(
                    [
                        "cmake", "-S", str(external_source), "-B", str(build),
                        f"-DCMAKE_PREFIX_PATH={prefix}",
                        f"-DBIVIDI_KIMERA_VIO_REVISION={PIN}",
                    ],
                    root,
                )
                self.assertEqual(configured.returncode, 0, configured.stdout)
                built = _run(["cmake", "--build", str(build), "--config", "Release"], root)
                self.assertEqual(built.returncode, 0, built.stdout)

                candidates = [
                    build / "bividi-kimera-link-probe",
                    build / "Release" / "bividi-kimera-link-probe.exe",
                    build / "bividi-kimera-link-probe.exe",
                ]
                executable = next((candidate for candidate in candidates if candidate.exists()), None)
                self.assertIsNotNone(executable, built.stdout)
                probe = _run([str(executable)], root)
                self.assertEqual(probe.returncode, 0, probe.stdout)
                self.assertIn(f"pinned_revision={PIN}", probe.stdout)
                self.assertIn(f"resolved_target_kind={expected[name]}", probe.stdout)

            missing = _run(
                ["cmake", "-S", str(external_source), "-B", str(root / "build-missing"),
                 f"-DCMAKE_PREFIX_PATH={fixtures['namespaced']}"],
                root,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("BIVIDI_KIMERA_VIO_REVISION", missing.stdout)

            wrong = _run(
                ["cmake", "-S", str(external_source), "-B", str(root / "build-wrong"),
                 f"-DCMAKE_PREFIX_PATH={fixtures['namespaced']}",
                 "-DBIVIDI_KIMERA_VIO_REVISION=deadbeef"],
                root,
            )
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("revision mismatch", wrong.stdout)

            bad_prefix = _write_bad_package(root)
            bad = _run(
                ["cmake", "-S", str(external_source), "-B", str(root / "build-bad"),
                 f"-DCMAKE_PREFIX_PATH={bad_prefix}",
                 f"-DBIVIDI_KIMERA_VIO_REVISION={PIN}"],
                root,
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("kimera_vio::kimera_vio", bad.stdout)
            self.assertIn("target exists", bad.stdout)


if __name__ == "__main__":
    unittest.main()
