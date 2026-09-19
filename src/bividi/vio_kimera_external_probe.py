"""Run the pinned Kimera-VIO external package/link probe and emit evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

SCHEMA = "bividi.vio.kimera_external_link_evidence.v1"
TOOL_VERSION = "1"
PINNED_REVISION = "ce8c59b7b273ab5ac29db7e5572e1623760e19c7"
TARGET_KINDS = {"build-tree-alias", "installed-export"}
PIN_RE = re.compile(r"pinned_revision=([0-9a-f]{40})")
TARGET_RE = re.compile(r"resolved_target_kind=([^\s]+)")


class ProbeInputError(ValueError):
    pass


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    output: str


def _run(command: Sequence[str], *, cwd: Path, timeout_s: int) -> CommandResult:
    try:
        proc = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeInputError(f"cannot execute {command[0]!r}: {exc}") from exc
    return CommandResult(list(command), proc.returncode, proc.stdout)


def _step(result: CommandResult) -> dict[str, object]:
    data = result.output.encode("utf-8", errors="replace")
    return {
        "command": result.command,
        "returncode": result.returncode,
        "output_sha256": hashlib.sha256(data).hexdigest(),
        "output_tail": result.output[-4000:],
    }


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute_probe(
    *,
    repo_root: Path,
    kimera_source: Path,
    build_dir: Path,
    evidence_out: Path,
    cmake_prefix: Path | None,
    kimera_vio_dir: Path | None,
    timeout_s: int = 300,
    evidence_kind: str = "real_external",
    expected_source_revision: str = PINNED_REVISION,
    package_source_binding: str = "operator_asserted",
) -> tuple[int, dict[str, object]]:
    repo_root = repo_root.resolve()
    kimera_source = kimera_source.resolve()
    build_dir = build_dir.resolve()
    evidence_out = evidence_out.resolve()
    cmake_prefix = cmake_prefix.resolve() if cmake_prefix is not None else None
    kimera_vio_dir = kimera_vio_dir.resolve() if kimera_vio_dir is not None else None

    if evidence_kind not in {"real_external", "synthetic"}:
        raise ProbeInputError("evidence_kind must be real_external or synthetic")
    if package_source_binding not in {"operator_asserted", "synthetic_fixture"}:
        raise ProbeInputError("invalid package_source_binding")
    if evidence_kind == "real_external" and expected_source_revision != PINNED_REVISION:
        raise ProbeInputError("real_external execution cannot override the pinned revision")
    if evidence_kind == "real_external" and package_source_binding != "operator_asserted":
        raise ProbeInputError("real_external package binding must be operator_asserted")
    if cmake_prefix is None and kimera_vio_dir is None:
        raise ProbeInputError("one of cmake_prefix or kimera_vio_dir is required")
    if not kimera_source.is_dir():
        raise ProbeInputError(f"Kimera source directory does not exist: {kimera_source}")

    evidence: dict[str, object] = {
        "schema": SCHEMA,
        "tool": "run_kimera_external_link_probe.py",
        "tool_version": TOOL_VERSION,
        "evidence_kind": evidence_kind,
        "status": "STARTED",
        "upstream": {
            "repository": "MIT-SPARK/Kimera-VIO",
            "pinned_revision": PINNED_REVISION,
        },
        "source": {
            "path": str(kimera_source),
            "expected_revision_for_execution": expected_source_revision,
        },
        "package": {
            "cmake_prefix_path": str(cmake_prefix) if cmake_prefix is not None else None,
            "kimera_vio_dir": str(kimera_vio_dir) if kimera_vio_dir is not None else None,
            "source_binding": package_source_binding,
            "source_binding_verified": False,
        },
        "build": {"directory": str(build_dir)},
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "steps": {},
        "claim_ceiling": (
            "Kimera external package/link probe only; package-to-source binding is not cryptographically "
            "verified; no StereoImuPipeline runtime, backend adoption, or VIO accuracy claim."
        ),
    }

    git_head = _run(["git", "-C", str(kimera_source), "rev-parse", "HEAD"], cwd=repo_root, timeout_s=timeout_s)
    evidence["steps"]["git_head"] = _step(git_head)  # type: ignore[index]
    if git_head.returncode != 0:
        evidence["status"] = "REJECTED_SOURCE_GIT"
        _write_evidence(evidence_out, evidence)
        return 2, evidence
    head = git_head.output.strip().lower()
    evidence["source"]["head_revision"] = head  # type: ignore[index]
    evidence["source"]["matches_upstream_pin"] = head == PINNED_REVISION  # type: ignore[index]
    if head != expected_source_revision:
        evidence["status"] = "REJECTED_SOURCE_REVISION"
        _write_evidence(evidence_out, evidence)
        return 2, evidence

    dirty = _run(
        ["git", "-C", str(kimera_source), "status", "--porcelain", "--untracked-files=normal"],
        cwd=repo_root,
        timeout_s=timeout_s,
    )
    evidence["steps"]["git_status"] = _step(dirty)  # type: ignore[index]
    if dirty.returncode != 0:
        evidence["status"] = "REJECTED_SOURCE_GIT"
        _write_evidence(evidence_out, evidence)
        return 2, evidence
    evidence["source"]["dirty"] = bool(dirty.output.strip())  # type: ignore[index]

    cmake_version = _run(["cmake", "--version"], cwd=repo_root, timeout_s=timeout_s)
    evidence["steps"]["cmake_version"] = _step(cmake_version)  # type: ignore[index]
    if cmake_version.returncode != 0:
        evidence["status"] = "REJECTED_CMAKE_UNAVAILABLE"
        _write_evidence(evidence_out, evidence)
        return 2, evidence
    evidence["platform"]["cmake"] = cmake_version.output.splitlines()[0] if cmake_version.output else ""  # type: ignore[index]

    configure_cmd = [
        "cmake", "-S", str(repo_root / "cmake" / "kimera-external"), "-B", str(build_dir),
        f"-DBIVIDI_KIMERA_VIO_REVISION={PINNED_REVISION}",
    ]
    if cmake_prefix is not None:
        configure_cmd.append(f"-DCMAKE_PREFIX_PATH={cmake_prefix}")
    if kimera_vio_dir is not None:
        configure_cmd.append(f"-Dkimera_vio_DIR={kimera_vio_dir}")
    configured = _run(configure_cmd, cwd=repo_root, timeout_s=timeout_s)
    evidence["steps"]["configure"] = _step(configured)  # type: ignore[index]
    if configured.returncode != 0:
        evidence["status"] = "FAIL_CONFIGURE"
        _write_evidence(evidence_out, evidence)
        return 3, evidence

    built = _run(
        ["cmake", "--build", str(build_dir), "--config", "Release", "--target", "bividi-kimera-link-probe"],
        cwd=repo_root,
        timeout_s=timeout_s,
    )
    evidence["steps"]["build"] = _step(built)  # type: ignore[index]
    if built.returncode != 0:
        evidence["status"] = "FAIL_BUILD"
        _write_evidence(evidence_out, evidence)
        return 3, evidence

    tested = _run(
        ["ctest", "--test-dir", str(build_dir), "-C", "Release", "-R", "^bividi_kimera_external_link_probe$", "-V"],
        cwd=repo_root,
        timeout_s=timeout_s,
    )
    evidence["steps"]["probe"] = _step(tested)  # type: ignore[index]
    if tested.returncode != 0:
        evidence["status"] = "FAIL_PROBE"
        _write_evidence(evidence_out, evidence)
        return 3, evidence

    pin_match = PIN_RE.search(tested.output)
    target_match = TARGET_RE.search(tested.output)
    reported_pin = pin_match.group(1) if pin_match else None
    target_kind = target_match.group(1) if target_match else None
    evidence["probe"] = {
        "reported_pinned_revision": reported_pin,
        "resolved_target_kind": target_kind,
    }
    if reported_pin != PINNED_REVISION or target_kind not in TARGET_KINDS:
        evidence["status"] = "FAIL_PROBE_OUTPUT"
        _write_evidence(evidence_out, evidence)
        return 3, evidence

    evidence["status"] = "PASS_REAL_EXTERNAL_LINK" if evidence_kind == "real_external" else "PASS_SYNTHETIC_FIXTURE"
    _write_evidence(evidence_out, evidence)
    return 0, evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the pinned Kimera-VIO external package/link probe")
    parser.add_argument("--kimera-source", required=True, type=Path)
    parser.add_argument("--cmake-prefix", type=Path)
    parser.add_argument("--kimera-vio-dir", type=Path)
    parser.add_argument("--build-dir", type=Path, default=Path("build-kimera"))
    parser.add_argument("--evidence-out", type=Path, default=Path("kimera-external-link-evidence.json"))
    parser.add_argument("--assert-package-built-from-source", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.assert_package_built_from_source:
        print(
            "--assert-package-built-from-source is required; the resulting package/source binding is recorded as operator_asserted",
            file=sys.stderr,
        )
        return 2
    if args.timeout_seconds <= 0:
        print("--timeout-seconds must be > 0", file=sys.stderr)
        return 2
    repo_root = Path(__file__).resolve().parents[2]
    try:
        rc, evidence = execute_probe(
            repo_root=repo_root,
            kimera_source=args.kimera_source,
            build_dir=args.build_dir,
            evidence_out=args.evidence_out,
            cmake_prefix=args.cmake_prefix,
            kimera_vio_dir=args.kimera_vio_dir,
            timeout_s=args.timeout_seconds,
        )
    except ProbeInputError as exc:
        print(f"kimera external link probe: {exc}", file=sys.stderr)
        return 2
    print(f"kimera external link probe: {evidence['status']}")
    print(f"evidence: {args.evidence_out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
