"""Hash-bind and gate the final stereo-calibration evidence bundle for issue #8.

Profiles:
  integrity  verify file hashes/schemas/cross-links
  review     integrity + no quality evidence may be FAIL
  promotion  review + all quality evidence must be explicit PASS with gates,
             measured provenance, immutable acquisition evidence, verified camera
             mapping, and a named policy source.

The gate owns no calibration thresholds. Numeric limits remain with the evidence
producers and must be justified by a lab/product policy.

This is the installed implementation for the legacy
``tools/stereo_calibration_provenance.py`` compatibility entry point.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

TARGET_SCHEMA = "bividi.calibration.stereo_target.v1"
TARGET_SCALE_SCHEMA = "bividi.calibration.stereo_target_scale_review.v1"
SESSION_SCHEMA = "bividi.calibration.stereo_session.v1"
QUALITY_SCHEMA = "bividi.calibration.stereo_dataset_quality.v1"
CALIB_SCHEMA = "bividi.calibration.stereo.v1"
GEOMETRY_SCHEMA = "bividi.calibration.stereo_geometry_review.v1"
REPEAT_SCHEMA = "bividi.calibration.stereo_repeatability.v1"
MANIFEST_SCHEMA = "bividi.calibration.stereo_evidence_manifest.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "stereo_calibration_provenance.py"
ROLES = {
    "target": TARGET_SCHEMA,
    "target_scale": TARGET_SCALE_SCHEMA,
    "session": SESSION_SCHEMA,
    "dataset_quality": QUALITY_SCHEMA,
    "calibration": CALIB_SCHEMA,
    "geometry_review": GEOMETRY_SCHEMA,
    "repeatability": REPEAT_SCHEMA,
}
QUALITY_ROLES = (
    "target_scale",
    "dataset_quality",
    "calibration",
    "geometry_review",
    "repeatability",
)
PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "unset", "none", "?"}


class GateError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{path}: expected object")
    return value


def placeholder(value: Any) -> bool:
    return not isinstance(value, str) or value.strip().lower() in PLACEHOLDERS


def rel(path: Path, owner: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), owner.parent.resolve()).replace(os.sep, "/")
    except ValueError:
        return str(path.resolve()).replace(os.sep, "/")


def resolve(owner: Path, text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else (owner.parent / path).resolve()


def record(role: str, path: Path, owner: Path) -> dict[str, Any]:
    data = load(path)
    expected = ROLES[role]
    if data.get("schema") != expected:
        raise GateError(f"{role}: expected {expected}; got {data.get('schema')!r}")
    return {
        "role": role,
        "path": rel(path, owner),
        "sha256": sha(path),
        "bytes": path.stat().st_size,
        "schema": expected,
    }


def verified(entry: Mapping[str, Any], owner: Path) -> tuple[Path, dict[str, Any]]:
    role = entry.get("role")
    if role not in ROLES:
        raise GateError(f"unknown evidence role {role!r}")
    path = resolve(owner, str(entry.get("path", "")))
    if not path.is_file():
        raise GateError(f"{role}: missing {path}")
    if sha(path) != entry.get("sha256"):
        raise GateError(f"{role}: SHA-256 mismatch")
    data = load(path)
    if data.get("schema") != ROLES[role]:
        raise GateError(f"{role}: schema mismatch")
    return path, data


def status_of(role: str, data: Mapping[str, Any]) -> str | None:
    if role == "calibration":
        quality = data.get("quality")
        return quality.get("status") if isinstance(quality, Mapping) else None
    return data.get("status") if isinstance(data.get("status"), str) else None


def gates_of(role: str, data: Mapping[str, Any]) -> Mapping[str, Any]:
    if role == "calibration":
        quality = data.get("quality")
        return (
            quality.get("gates", {})
            if isinstance(quality, Mapping) and isinstance(quality.get("gates"), Mapping)
            else {}
        )
    gates = data.get("gates")
    return gates if isinstance(gates, Mapping) else {}


def policy_of(role: str, data: Mapping[str, Any]) -> Any:
    if role == "calibration":
        quality = data.get("quality")
        return quality.get("policy_source") if isinstance(quality, Mapping) else None
    return data.get("policy_source")


def _check_bound_path(
    owner: Path,
    entry: Mapping[str, Any],
    label: str,
    findings: list[str],
) -> None:
    path_text = entry.get("path")
    expected_hash = entry.get("sha256")
    if (
        not isinstance(path_text, str)
        or not path_text
        or not isinstance(expected_hash, str)
        or len(expected_hash) != 64
    ):
        findings.append(f"{label} path/hash binding is malformed")
        return
    path = resolve(owner, path_text)
    if not path.is_file():
        findings.append(f"{label} is missing: {path}")
        return
    if sha(path) != expected_hash:
        findings.append(f"{label} SHA-256 mismatch")


def check_session_sources(
    session: Mapping[str, Any],
    session_path: Path,
    require_promotion_sources: bool,
) -> list[str]:
    findings: list[str] = []
    trace = session.get("source_trace")
    if trace is None:
        if require_promotion_sources:
            findings.append("promotion requires session.source_trace acquisition evidence")
    elif not isinstance(trace, Mapping):
        findings.append("session.source_trace is malformed")
    else:
        artifacts = trace.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            findings.append("session.source_trace.artifacts must be non-empty")
        else:
            roles = set()
            for index, entry in enumerate(artifacts):
                if not isinstance(entry, Mapping):
                    findings.append(f"session.source_trace.artifacts[{index}] is malformed")
                    continue
                role = entry.get("role")
                if not isinstance(role, str) or not role or role in roles:
                    findings.append(
                        f"session.source_trace.artifacts[{index}] has invalid/duplicate role"
                    )
                    continue
                roles.add(role)
                _check_bound_path(
                    session_path,
                    entry,
                    f"session.source_trace.{role}",
                    findings,
                )

    pairs = session.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        findings.append("session has no stereo pairs")
        return findings
    for index, pair in enumerate(pairs):
        if not isinstance(pair, Mapping):
            findings.append(f"session pair {index} is malformed")
            continue
        for camera in ("camera_a", "camera_b"):
            path_text = pair.get(camera)
            hash_text = pair.get(camera + "_sha256")
            if require_promotion_sources and (
                not isinstance(hash_text, str) or len(hash_text) != 64
            ):
                findings.append(
                    f"promotion requires immutable {camera} hash for pair {pair.get('pair_id', index)}"
                )
                continue
            if isinstance(hash_text, str):
                _check_bound_path(
                    session_path,
                    {"path": path_text, "sha256": hash_text},
                    f"session pair {pair.get('pair_id', index)} {camera}",
                    findings,
                )
    return findings


def cross_check(
    data: Mapping[str, dict[str, Any]],
    paths: Mapping[str, Path],
    promotion: bool = False,
) -> list[str]:
    findings: list[str] = []
    target, scale, session, quality, calib, geometry, repeat = [
        data[key]
        for key in (
            "target",
            "target_scale",
            "session",
            "dataset_quality",
            "calibration",
            "geometry_review",
            "repeatability",
        )
    ]
    target_hash = sha(paths["target"])
    session_hash = sha(paths["session"])
    calib_hash = sha(paths["calibration"])
    if scale.get("target", {}).get("sha256") != target_hash:
        findings.append("target_scale does not bind selected target")
    if session.get("target", {}).get("sha256") != target_hash:
        findings.append("session does not bind selected target")
    if quality.get("session", {}).get("sha256") != session_hash:
        findings.append("dataset_quality does not bind selected session")
    if quality.get("target", {}).get("sha256") != target_hash:
        findings.append("dataset_quality does not bind selected target")
    provenance = calib.get("provenance", {})
    if provenance.get("source_session_sha256") != session_hash:
        findings.append("calibration does not bind selected session")
    if calib.get("target", {}).get("sha256") != target_hash:
        findings.append("calibration does not bind selected target")
    if geometry.get("calibration", {}).get("sha256") != calib_hash:
        findings.append("geometry_review does not bind selected calibration")
    artifacts = repeat.get("artifacts", [])
    hashes = {entry.get("sha256") for entry in artifacts if isinstance(entry, Mapping)}
    if calib_hash not in hashes:
        findings.append("repeatability campaign does not include selected calibration")
    if calib.get("device") != session.get("device"):
        findings.append("calibration device identity differs from session")
    calibration_capture = calib.get("capture", {})
    session_capture = session.get("capture", {})
    for key in ("mode_index", "pixel_format", "width", "height"):
        if calibration_capture.get(key) != session_capture.get(key):
            findings.append(f"calibration capture.{key} differs from session")
    findings.extend(check_session_sources(session, paths["session"], promotion))
    return findings


def build(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    selected = {key: getattr(args, key).resolve() for key in ROLES}
    docs = {key: load(path) for key, path in selected.items()}
    for key, data in docs.items():
        if data.get("schema") != ROLES[key]:
            raise GateError(f"{key}: expected {ROLES[key]}")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "created_utc": utc_now(),
        "profile": args.profile,
        "policy_source": args.policy_source,
        "evidence": [record(key, selected[key], output) for key in ROLES],
        "provenance": {
            "tool": COMPATIBILITY_TOOL_NAME,
            "tool_version": TOOL_VERSION,
        },
    }
    return evaluate(manifest, output, docs_override=docs, paths_override=selected)


def evidence_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    entries = manifest.get("evidence")
    if not isinstance(entries, list):
        raise GateError("evidence array required")
    result: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise GateError("invalid evidence entry")
        role = entry.get("role")
        if role in result:
            raise GateError(f"duplicate role {role}")
        result[role] = entry
    missing = set(ROLES) - set(result)
    if missing:
        raise GateError("missing evidence roles: " + ", ".join(sorted(missing)))
    return result


def evaluate(
    manifest: dict[str, Any],
    owner: Path,
    docs_override: Mapping[str, dict[str, Any]] | None = None,
    paths_override: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise GateError(f"expected {MANIFEST_SCHEMA}")
    entries = evidence_map(manifest)
    docs: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    if docs_override is None:
        for role, entry in entries.items():
            paths[role], docs[role] = verified(entry, owner)
    else:
        if paths_override is None:
            raise GateError("paths_override is required with docs_override")
        docs = dict(docs_override)
        paths = dict(paths_override)
    profile = manifest.get("profile")
    if profile not in {"integrity", "review", "promotion"}:
        raise GateError("profile must be integrity/review/promotion")
    findings = cross_check(docs, paths, promotion=(profile == "promotion"))
    quality_status = {role: status_of(role, docs[role]) for role in QUALITY_ROLES}
    if profile in {"review", "promotion"}:
        for role, status in quality_status.items():
            if status == "FAIL":
                findings.append(f"{role} status is FAIL")
    if profile == "promotion":
        if placeholder(manifest.get("policy_source")):
            findings.append("promotion requires non-placeholder manifest policy_source")
        if docs["session"].get("provenance", {}).get("kind") != "measured":
            findings.append("promotion requires measured session provenance")
        if docs["calibration"].get("provenance", {}).get("kind") != "measured":
            findings.append("promotion requires measured calibration provenance")
        mapping = docs["session"].get("capture", {}).get("camera_mapping_evidence")
        if placeholder(mapping):
            findings.append(
                "promotion requires #35 camera mapping evidence in session.capture.camera_mapping_evidence"
            )
        for role in QUALITY_ROLES:
            status = quality_status[role]
            if status != "PASS":
                findings.append(f"promotion requires {role} status PASS; got {status!r}")
            if not gates_of(role, docs[role]):
                findings.append(f"promotion requires explicit gates in {role}")
            if placeholder(policy_of(role, docs[role])):
                findings.append(f"promotion requires {role} policy_source")
    if profile == "promotion" and not findings:
        disposition = "PROMOTION_READY"
    elif profile == "review" and not findings:
        disposition = "REVIEWABLE"
    elif profile == "integrity" and not findings:
        disposition = "INTEGRITY_OK"
    else:
        disposition = "FAIL"
    result = dict(manifest)
    result["quality_status"] = quality_status
    result["findings"] = findings
    result["disposition"] = disposition
    return result


def verify(path: Path) -> dict[str, Any]:
    return evaluate(load(path), path)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        output = root / "manifest.json"
        target = {"schema": TARGET_SCHEMA, "target_id": "t"}
        target_path = root / "target.json"
        target_path.write_text(json.dumps(target), encoding="utf-8")
        target_hash = sha(target_path)

        capture_path = root / "capture.json"
        frames_path = root / "frames.csv"
        camera_a_path = root / "a.png"
        camera_b_path = root / "b.png"
        capture_path.write_text("{}", encoding="utf-8")
        frames_path.write_text("frame_index\n0\n", encoding="utf-8")
        camera_a_path.write_bytes(b"a")
        camera_b_path.write_bytes(b"b")
        session = {
            "schema": SESSION_SCHEMA,
            "session_id": "s",
            "provenance": {"kind": "measured"},
            "device": {"model": "M", "serial": "S"},
            "capture": {
                "mode_index": 0,
                "pixel_format": "GRAY8",
                "width": 640,
                "height": 480,
                "camera_mapping_evidence": "#35 physical mapping note",
            },
            "target": {"sha256": target_hash},
            "source_trace": {
                "kind": "test-recorder",
                "artifacts": [
                    {
                        "role": "capture_manifest",
                        "path": "capture.json",
                        "sha256": sha(capture_path),
                    },
                    {
                        "role": "frames_csv",
                        "path": "frames.csv",
                        "sha256": sha(frames_path),
                    },
                ],
            },
            "pairs": [
                {
                    "pair_id": "p0",
                    "camera_a": "a.png",
                    "camera_b": "b.png",
                    "camera_a_sha256": sha(camera_a_path),
                    "camera_b_sha256": sha(camera_b_path),
                }
            ],
        }
        session_path = root / "session.json"
        session_path.write_text(json.dumps(session), encoding="utf-8")
        session_hash = sha(session_path)
        scale = {
            "schema": TARGET_SCALE_SCHEMA,
            "target": {"sha256": target_hash},
            "status": "PASS",
            "gates": {"g": {"pass": True}},
            "policy_source": "lab-v1",
        }
        quality = {
            "schema": QUALITY_SCHEMA,
            "session": {"sha256": session_hash},
            "target": {"sha256": target_hash},
            "status": "PASS",
            "gates": {"g": {"pass": True}},
            "policy_source": "lab-v1",
        }
        calib = {
            "schema": CALIB_SCHEMA,
            "calibration_id": "c",
            "provenance": {
                "kind": "measured",
                "source_session_sha256": session_hash,
            },
            "device": session["device"],
            "capture": session["capture"],
            "target": {"sha256": target_hash},
            "quality": {
                "status": "PASS",
                "gates": {"g": {"pass": True}},
                "policy_source": "lab-v1",
            },
        }
        calib_path = root / "calib.json"
        calib_path.write_text(json.dumps(calib), encoding="utf-8")
        calib_hash = sha(calib_path)
        geometry = {
            "schema": GEOMETRY_SCHEMA,
            "calibration": {"sha256": calib_hash},
            "status": "PASS",
            "gates": {"g": {"pass": True}},
            "policy_source": "lab-v1",
        }
        repeat = {
            "schema": REPEAT_SCHEMA,
            "artifacts": [{"sha256": calib_hash}],
            "status": "PASS",
            "gates": {"g": {"pass": True}},
            "policy_source": "lab-v1",
        }
        files: dict[str, Path] = {
            "target": target_path,
            "session": session_path,
            "calibration": calib_path,
        }
        for name, data in (
            ("target_scale", scale),
            ("dataset_quality", quality),
            ("geometry_review", geometry),
            ("repeatability", repeat),
        ):
            path = root / (name + ".json")
            path.write_text(json.dumps(data), encoding="utf-8")
            files[name] = path
        namespace = argparse.Namespace(
            output=output,
            profile="promotion",
            policy_source="lab-v1",
            **files,
        )
        manifest = build(namespace)
        assert manifest["disposition"] == "PROMOTION_READY", manifest["findings"]
        assert manifest["provenance"]["tool"] == COMPATIBILITY_TOOL_NAME
        output.write_text(json.dumps(manifest), encoding="utf-8")
        assert verify(output)["disposition"] == "PROMOTION_READY"
        camera_a_path.write_bytes(b"changed")
        assert verify(output)["disposition"] == "FAIL"
    print("Stereo calibration evidence promotion gate self-test: PASS")


def parse(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    build_parser = sub.add_parser("build")
    for role in ROLES:
        build_parser.add_argument(
            "--" + role.replace("_", "-"),
            dest=role,
            type=Path,
            required=True,
        )
    build_parser.add_argument(
        "--profile",
        choices=("integrity", "review", "promotion"),
        required=True,
    )
    build_parser.add_argument("--policy-source")
    build_parser.add_argument("--output", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("manifest", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    if args.self_test:
        self_test()
        return 0
    if args.cmd == "build":
        manifest = build(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(manifest["disposition"])
        return 0 if manifest["disposition"] != "FAIL" else 3
    if args.cmd == "verify":
        manifest = verify(args.manifest.resolve())
        print(json.dumps(manifest, indent=2))
        return 0 if manifest["disposition"] != "FAIL" else 3
    raise GateError("choose build/verify or --self-test")


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """CLI wrapper preserving historical usage/domain exit code 2."""

    try:
        return main(argv)
    except GateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
