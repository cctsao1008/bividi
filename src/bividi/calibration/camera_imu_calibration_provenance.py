#!/usr/bin/env python3
"""Build and verify a provenance-bound camera↔IMU calibration evidence manifest.

This is the final review/promotion boundary for issue #47. It does not solve or
change calibration numbers. It hash-binds the independent evidence classes,
re-verifies their cross-links, and applies one of three policy profiles:

  integrity  hashes/schemas/cross-links only
  review     integrity + no evidence report may be FAIL
  promotion  review + every quality report must be explicit PASS and a named
             lab/product policy source must be recorded

Numeric thresholds remain owned by the individual evidence tools. This gate
never invents universal camera↔IMU acceptance limits.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import artifact_validator as validate_calibration_artifact

MANIFEST_SCHEMA = "bividi.calibration.camera_imu_evidence_manifest.v1"
TOOL_VERSION = "1"
BACKEND = "ethz-asl/kalibr"
PINNED_KALIBR_REVISION = "1f60227442d25e36365ef5f72cd80b9666d73467"
TIME_OFFSET_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"

ROLE_SCHEMAS = {
    "dynamic_session": "bividi.calibration.kalibr_dynamic_session.v1",
    "excitation": "bividi.calibration.camera_imu_excitation.v1",
    "target_observations": "bividi.calibration.kalibr_target_observations.v1",
    "target_coverage": "bividi.calibration.kalibr_target_coverage.v1",
    "solver_quality": "bividi.calibration.kalibr_solver_quality.v1",
    "import_manifest": "bividi.calibration.kalibr_camera_imu_import.v1",
    "candidate": "bividi.calibration.camera_imu.v1",
    "time_review": "bividi.calibration.camera_imu_time_review.v1",
    "repeatability": "bividi.calibration.camera_imu_repeatability.v1",
}

INPUT_ROLES = (
    "dynamic_session",
    "excitation",
    "target_coverage",
    "solver_quality",
    "import_manifest",
    "candidate",
    "time_review",
    "repeatability",
)

QUALITY_ROLES = ("excitation", "target_coverage", "solver_quality", "time_review", "repeatability")
PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "unset", "none", "?"}


class GateError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{path}: expected JSON object")
    return value


def nested(data: Mapping[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def placeholder(value: Any) -> bool:
    return not isinstance(value, str) or value.strip().lower() in PLACEHOLDERS


def manifest_relpath(path: Path, manifest_path: Path) -> str:
    absolute = path.resolve()
    base = manifest_path.parent.resolve()
    try:
        return os.path.relpath(absolute, base).replace(os.sep, "/")
    except ValueError:
        return str(absolute).replace(os.sep, "/")


def resolve_from(owner: Path, text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else (owner.parent / path).resolve()


def file_record(role: str, path: Path, manifest_path: Path, schema: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise GateError(f"{role}: file does not exist: {path}")
    result: dict[str, Any] = {
        "role": role,
        "path": manifest_relpath(path, manifest_path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if schema is not None:
        data = load_json(path)
        if data.get("schema") != schema:
            raise GateError(f"{role}: expected schema {schema!r}; got {data.get('schema')!r}")
        result["schema"] = schema
    return result


def verify_record(entry: Mapping[str, Any], owner: Path, *, expected_schema: str | None = None) -> tuple[Path, dict[str, Any] | None]:
    role = entry.get("role")
    raw_path = entry.get("path")
    expected_hash = entry.get("sha256")
    if not nonempty(role) or not nonempty(raw_path) or not nonempty(expected_hash):
        raise GateError("manifest file record requires role/path/sha256")
    path = resolve_from(owner, str(raw_path))
    if not path.is_file():
        raise GateError(f"{role}: bound file is missing: {path}")
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise GateError(f"{role}: SHA-256 mismatch for {path}")
    expected_bytes = entry.get("bytes")
    if isinstance(expected_bytes, int) and expected_bytes >= 0 and path.stat().st_size != expected_bytes:
        raise GateError(f"{role}: byte-size mismatch for {path}")
    schema = expected_schema or entry.get("schema")
    if schema is None:
        return path, None
    data = load_json(path)
    if data.get("schema") != schema:
        raise GateError(f"{role}: expected schema {schema!r}; got {data.get('schema')!r}")
    return path, data


def verified_ref(owner: Path, entry: Any, label: str, expected_schema: str | None = None) -> tuple[Path, dict[str, Any] | None]:
    if not isinstance(entry, Mapping) or not nonempty(entry.get("path")) or not nonempty(entry.get("sha256")):
        raise GateError(f"{label}: path/SHA-256 reference required")
    path = resolve_from(owner, str(entry["path"]))
    if not path.is_file():
        raise GateError(f"{label}: referenced file does not exist: {path}")
    if sha256_file(path) != entry["sha256"]:
        raise GateError(f"{label}: referenced file SHA-256 mismatch: {path}")
    if expected_schema is None:
        return path, None
    data = load_json(path)
    if data.get("schema") != expected_schema:
        raise GateError(f"{label}: expected schema {expected_schema!r}; got {data.get('schema')!r}")
    return path, data


def validate_candidate(path: Path, data: Mapping[str, Any]) -> None:
    findings = validate_calibration_artifact.validate(dict(data))
    errors = [finding for finding in findings if finding.severity == "error"]
    if errors:
        rendered = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise GateError(f"candidate {path}: calibration artifact validation failed: {rendered}")


def verify_dynamic_session_sources(path: Path, session: Mapping[str, Any]) -> None:
    sources = session.get("sources")
    if not isinstance(sources, Mapping):
        raise GateError(f"{path}: dynamic session has no sources map")
    for key, entry in sources.items():
        verified_ref(path, entry, f"dynamic_session.sources.{key}")


def evidence_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    entries = manifest.get("evidence")
    if not isinstance(entries, list):
        raise GateError("manifest.evidence must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not nonempty(entry.get("role")):
            raise GateError("manifest.evidence contains invalid entry")
        role = str(entry["role"])
        if role in result:
            raise GateError(f"duplicate evidence role {role!r}")
        if role not in ROLE_SCHEMAS:
            raise GateError(f"unknown evidence role {role!r}")
        result[role] = entry
    missing = sorted(set(ROLE_SCHEMAS) - set(result))
    if missing:
        raise GateError(f"manifest missing evidence role(s): {', '.join(missing)}")
    return result


def support_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    entries = manifest.get("supporting_files")
    if not isinstance(entries, list):
        raise GateError("manifest.supporting_files must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not nonempty(entry.get("role")):
            raise GateError("manifest.supporting_files contains invalid entry")
        role = str(entry["role"])
        if role in result:
            raise GateError(f"duplicate supporting-file role {role!r}")
        result[role] = entry
    for required in ("kalibr_result_yaml", "kalibr_results_imucam_txt"):
        if required not in result:
            raise GateError(f"manifest missing supporting file {required!r}")
    return result


def report_status(role: str, data: Mapping[str, Any]) -> str:
    if role in ("excitation", "target_coverage", "solver_quality"):
        value = nested(data, "assessment", "status")
    else:
        value = data.get("status")
    if value not in {"PASS", "FAIL", "EVIDENCE_ONLY_NO_THRESHOLDS"}:
        raise GateError(f"{role}: unsupported/missing report status {value!r}")
    return str(value)


def has_explicit_gates(role: str, data: Mapping[str, Any]) -> bool:
    if role in ("excitation", "solver_quality"):
        gates = nested(data, "assessment", "gates")
        return isinstance(gates, list) and len(gates) > 0
    if role == "target_coverage":
        thresholds = nested(data, "assessment", "thresholds")
        return isinstance(thresholds, Mapping) and any(value is not None for value in thresholds.values())
    if role in ("time_review", "repeatability"):
        gates = data.get("gates")
        return isinstance(gates, list) and len(gates) > 0
    return False


def camera_compatibility_key(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "device_model": nested(candidate, "device", "model"),
        "device_serial": nested(candidate, "device", "serial"),
        "camera_id": nested(candidate, "camera_reference", "camera_id"),
        "camera_frame": nested(candidate, "camera_reference", "frame"),
        "camera_width": nested(candidate, "camera_reference", "width"),
        "camera_height": nested(candidate, "camera_reference", "height"),
        "camera_mode_id": nested(candidate, "camera_reference", "mode_id"),
        "imu_model": nested(candidate, "imu_reference", "model"),
        "imu_frame": nested(candidate, "imu_reference", "frame"),
        "transform_from": nested(candidate, "transform", "from_frame"),
        "transform_to": nested(candidate, "transform", "to_frame"),
        "translation_unit": nested(candidate, "transform", "translation_unit"),
        "handedness": nested(candidate, "frames", "handedness"),
        "camera_axes": nested(candidate, "frames", "camera_axes"),
        "imu_axes": nested(candidate, "frames", "imu_axes"),
        "time_definition": nested(candidate, "time_offset", "definition"),
        "camera_time_reference": nested(candidate, "time_offset", "camera_time_reference"),
        "external_backend": nested(candidate, "provenance", "external_backend"),
    }


def require_equal(label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        raise GateError(f"{label}: {observed!r} != {expected!r}")


def verify_repeatability_artifacts(report_path: Path, report: Mapping[str, Any], candidate_hash: str,
                                   candidate: Mapping[str, Any]) -> None:
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) < 2:
        raise GateError("repeatability: expected at least two artifact references")
    hashes: list[str] = []
    candidate_count = 0
    expected_contract = camera_compatibility_key(candidate)
    for index, entry in enumerate(artifacts):
        if not isinstance(entry, Mapping):
            raise GateError(f"repeatability.artifacts[{index}] is invalid")
        path, data = verified_ref(report_path, entry, f"repeatability.artifacts[{index}]", ROLE_SCHEMAS["candidate"])
        assert data is not None
        validate_candidate(path, data)
        digest = sha256_file(path)
        hashes.append(digest)
        if digest == candidate_hash:
            candidate_count += 1
        current = camera_compatibility_key(data)
        if current != expected_contract:
            differences = [key for key in expected_contract if current.get(key) != expected_contract.get(key)]
            raise GateError(
                f"repeatability.artifacts[{index}] incompatible with candidate: "
                + ", ".join(differences)
            )
    if len(set(hashes)) != len(hashes):
        raise GateError("repeatability: duplicate artifact content in report")
    if candidate_count != 1:
        raise GateError(f"repeatability: promoted candidate must appear exactly once; found {candidate_count}")
    contract = report.get("compatibility_contract")
    if not isinstance(contract, Mapping):
        raise GateError("repeatability: missing compatibility_contract")
    for key, expected in expected_contract.items():
        require_equal(f"repeatability.compatibility_contract.{key}", contract.get(key), expected)


def verify_nested_links(paths: Mapping[str, Path], data: Mapping[str, Mapping[str, Any]],
                        support_paths: Mapping[str, Path]) -> dict[str, Any]:
    session_path = paths["dynamic_session"]
    session = data["dynamic_session"]
    candidate_path = paths["candidate"]
    candidate = data["candidate"]
    session_hash = sha256_file(session_path)
    candidate_hash = sha256_file(candidate_path)

    verify_dynamic_session_sources(session_path, session)
    validate_candidate(candidate_path, candidate)

    kalibr = session.get("kalibr")
    if not isinstance(kalibr, Mapping):
        raise GateError("dynamic_session.kalibr object required")
    require_equal("dynamic_session.kalibr.backend", kalibr.get("backend"), BACKEND)
    revision = kalibr.get("revision")
    if not nonempty(revision):
        raise GateError("dynamic_session.kalibr.revision is required")

    time_ref = session.get("camera_time_reference")
    if not isinstance(time_ref, Mapping):
        raise GateError("dynamic_session.camera_time_reference object required")
    require_equal("dynamic_session.camera_time_reference.time_shift_definition",
                  time_ref.get("time_shift_definition"), TIME_OFFSET_DEFINITION)
    camera_time_reference = time_ref.get("kind")
    if camera_time_reference not in {"exposure_start", "exposure_midpoint", "exposure_end"}:
        raise GateError(f"unsupported camera timestamp semantic {camera_time_reference!r}")

    mapping = session.get("camera_mapping")
    if not isinstance(mapping, Mapping):
        raise GateError("dynamic_session.camera_mapping object required")

    provenance = candidate.get("provenance")
    if not isinstance(provenance, Mapping):
        raise GateError("candidate.provenance object required")
    require_equal("candidate.provenance.kind", provenance.get("kind"), "imported")
    require_equal("candidate.provenance.source_hash", provenance.get("source_hash"), session_hash)
    require_equal("candidate.provenance.external_backend", provenance.get("external_backend"), BACKEND)
    require_equal("candidate.provenance.external_backend_revision", provenance.get("external_backend_revision"), revision)
    require_equal("candidate.time_offset.definition", nested(candidate, "time_offset", "definition"), TIME_OFFSET_DEFINITION)
    require_equal("candidate.time_offset.camera_time_reference",
                  nested(candidate, "time_offset", "camera_time_reference"), camera_time_reference)
    require_equal("candidate.transform.from_frame", nested(candidate, "transform", "from_frame"), nested(candidate, "imu_reference", "frame"))
    require_equal("candidate.transform.to_frame", nested(candidate, "transform", "to_frame"), nested(candidate, "camera_reference", "frame"))
    if nested(session, "device", "serial") is not None:
        require_equal("candidate.device.serial", nested(candidate, "device", "serial"), nested(session, "device", "serial"))

    excitation = data["excitation"]
    require_equal("excitation.source.dynamic_session.sha256",
                  nested(excitation, "source", "dynamic_session", "sha256"), session_hash)
    require_equal("excitation.session_context.kalibr.revision",
                  nested(excitation, "session_context", "kalibr", "revision"), revision)
    require_equal("excitation.session_context.camera_time_reference",
                  nested(excitation, "session_context", "camera_time_reference"), time_ref)

    observations = data["target_observations"]
    require_equal("target_observations.session.sha256", nested(observations, "session", "sha256"), session_hash)
    require_equal("target_observations.kalibr.backend", nested(observations, "kalibr", "backend"), BACKEND)
    require_equal("target_observations.kalibr.revision", nested(observations, "kalibr", "revision"), revision)

    coverage = data["target_coverage"]
    require_equal("target_coverage.source.sha256", nested(coverage, "source", "sha256"), sha256_file(paths["target_observations"]))
    require_equal("target_coverage.kalibr.revision", nested(coverage, "kalibr", "revision"), revision)

    solver = data["solver_quality"]
    require_equal("solver_quality.source.dynamic_session.sha256",
                  nested(solver, "source", "dynamic_session", "sha256"), session_hash)
    require_equal("solver_quality.source_contract.backend", nested(solver, "source_contract", "backend"), BACKEND)
    require_equal("solver_quality.source_contract.session_revision", nested(solver, "source_contract", "session_revision"), revision)
    require_equal("solver_quality.source.results_imucam_txt.sha256",
                  nested(solver, "source", "results_imucam_txt", "sha256"),
                  sha256_file(support_paths["kalibr_results_imucam_txt"]))

    imported = data["import_manifest"]
    require_equal("import_manifest.dynamic_session.sha256", nested(imported, "dynamic_session", "sha256"), session_hash)
    require_equal("import_manifest.output_artifact.sha256", nested(imported, "output_artifact", "sha256"), candidate_hash)
    require_equal("import_manifest.artifact_calibration_id", imported.get("artifact_calibration_id"), candidate.get("calibration_id"))
    require_equal("import_manifest.kalibr_revision", imported.get("kalibr_revision"), revision)
    require_equal("import_manifest.camera_time_reference", imported.get("camera_time_reference"), camera_time_reference)
    require_equal("import_manifest.time_shift_definition", imported.get("time_shift_definition"), TIME_OFFSET_DEFINITION)
    require_equal("import_manifest.status", imported.get("status"), "imported_candidate_requires_review")
    camera_id = imported.get("camera_id")
    kalibr_camera = imported.get("camera")
    if not nonempty(camera_id) or not nonempty(kalibr_camera):
        raise GateError("import_manifest camera/camera_id are required")
    require_equal(f"dynamic_session.camera_mapping.{camera_id}", mapping.get(str(camera_id)), kalibr_camera)
    require_equal("candidate.camera_reference.camera_id", nested(candidate, "camera_reference", "camera_id"), camera_id)
    require_equal("import_manifest.kalibr_result.sha256", nested(imported, "kalibr_result", "sha256"),
                  sha256_file(support_paths["kalibr_result_yaml"]))

    solver_report_ref = imported.get("solver_report")
    if solver_report_ref is not None:
        path, _ = verified_ref(paths["import_manifest"], solver_report_ref, "import_manifest.solver_report")
        if "import_solver_report" in support_paths:
            require_equal("import_manifest.solver_report.sha256", sha256_file(path), sha256_file(support_paths["import_solver_report"]))

    time_review = data["time_review"]
    require_equal("time_review.dynamic_session.sha256", nested(time_review, "dynamic_session", "sha256"), session_hash)
    require_equal("time_review.camera_imu_artifact.sha256", nested(time_review, "camera_imu_artifact", "sha256"), candidate_hash)
    require_equal("time_review.camera_time_reference", time_review.get("camera_time_reference"), camera_time_reference)
    require_equal("time_review.time_offset.definition", nested(time_review, "time_offset", "definition"), TIME_OFFSET_DEFINITION)
    candidate_offset = nested(candidate, "time_offset", "offset_s")
    reviewed_offset = nested(time_review, "time_offset", "kalibr_offset_s")
    if not isinstance(candidate_offset, (int, float)) or isinstance(candidate_offset, bool) or not math.isfinite(float(candidate_offset)):
        raise GateError("candidate.time_offset.offset_s is invalid")
    if not isinstance(reviewed_offset, (int, float)) or isinstance(reviewed_offset, bool) or not math.isfinite(float(reviewed_offset)):
        raise GateError("time_review.time_offset.kalibr_offset_s is invalid")
    if abs(float(candidate_offset) - float(reviewed_offset)) > 1e-15:
        raise GateError("time_review offset value does not equal candidate offset")

    repeatability = data["repeatability"]
    verify_repeatability_artifacts(paths["repeatability"], repeatability, candidate_hash, candidate)
    revisions = nested(repeatability, "compatibility_contract", "backend_revisions")
    if isinstance(revisions, list) and any(value != revision for value in revisions):
        raise GateError("repeatability backend revision set differs from candidate/session revision")

    return {
        "dynamic_session_sha256": session_hash,
        "session_id": session.get("session_id"),
        "kalibr_backend": BACKEND,
        "kalibr_revision": revision,
        "camera_id": camera_id,
        "kalibr_camera": kalibr_camera,
        "camera_frame": nested(candidate, "camera_reference", "frame"),
        "imu_frame": nested(candidate, "imu_reference", "frame"),
        "camera_time_reference": camera_time_reference,
        "time_shift_definition": TIME_OFFSET_DEFINITION,
        "candidate_calibration_id": candidate.get("calibration_id"),
        "candidate_sha256": candidate_hash,
        "device_serial": nested(candidate, "device", "serial"),
    }


def assess(profile: str, data: Mapping[str, Mapping[str, Any]], policy_source: Any) -> dict[str, Any]:
    if profile not in {"integrity", "review", "promotion"}:
        raise GateError(f"unsupported profile {profile!r}")
    statuses = {role: report_status(role, data[role]) for role in QUALITY_ROLES}
    failures: list[str] = []
    warnings: list[str] = []

    if profile in {"review", "promotion"}:
        failures.extend(f"{role}: report status FAIL" for role, status in statuses.items() if status == "FAIL")
        warnings.extend(
            f"{role}: evidence-only; no explicit numeric acceptance gates were applied"
            for role, status in statuses.items() if status == "EVIDENCE_ONLY_NO_THRESHOLDS"
        )
    else:
        warnings.extend(f"{role}: report status {status}" for role, status in statuses.items() if status != "PASS")

    if profile == "promotion":
        if placeholder(policy_source):
            failures.append("promotion requires a non-placeholder policy_source naming the lab/product acceptance basis")
        for role, status in statuses.items():
            if status != "PASS":
                failures.append(f"{role}: promotion requires explicit PASS, observed {status}")
            elif not has_explicit_gates(role, data[role]):
                failures.append(f"{role}: PASS lacks explicit gate evidence")
        if nested(data["target_observations"], "kalibr", "reviewed_revision") is not True:
            failures.append("target_observations: Kalibr detector revision is not marked reviewed")
        if nested(data["solver_quality"], "source_contract", "revision_mismatch_allowed") is not False:
            failures.append("solver_quality: promotion forbids an allowed Kalibr parser/backend revision mismatch")
        if nested(data["target_observations"], "kalibr", "revision") != PINNED_KALIBR_REVISION:
            failures.append("target_observations: promotion currently requires the reviewed pinned Kalibr revision")

    if failures:
        disposition = "BLOCKED"
        status = "FAIL"
    elif profile == "integrity":
        disposition = "INTEGRITY_VERIFIED"
        status = "PASS"
    elif profile == "review":
        disposition = "REVIEW_READY"
        status = "PASS"
    else:
        disposition = "PROMOTION_READY"
        status = "PASS"

    return {
        "profile": profile,
        "status": status,
        "disposition": disposition,
        "evidence_statuses": statuses,
        "failures": failures,
        "warnings": warnings,
        "policy_source": policy_source,
        "semantics": {
            "integrity": "hash/schema/cross-link consistency only; quality status does not gate this profile",
            "review": "all evidence is compatible and no component report is FAIL; evidence-only reports are allowed",
            "promotion": "all quality reports must be explicit PASS under recorded thresholds and a named acceptance policy",
        },
    }


def load_bound_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]], dict[str, Path]]:
    manifest = load_json(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise GateError(f"{manifest_path}: expected schema {MANIFEST_SCHEMA!r}")
    entries = evidence_map(manifest)
    paths: dict[str, Path] = {}
    data: dict[str, dict[str, Any]] = {}
    for role, entry in entries.items():
        path, loaded = verify_record(entry, manifest_path, expected_schema=ROLE_SCHEMAS[role])
        assert loaded is not None
        paths[role] = path
        data[role] = loaded

    supports = support_map(manifest)
    support_paths: dict[str, Path] = {}
    for role, entry in supports.items():
        path, _ = verify_record(entry, manifest_path)
        support_paths[role] = path
    return manifest, paths, data, support_paths


def verify_manifest(manifest_path: Path, profile: str) -> dict[str, Any]:
    manifest, paths, data, support_paths = load_bound_manifest(manifest_path)
    compatibility = verify_nested_links(paths, data, support_paths)
    recorded = manifest.get("compatibility")
    if not isinstance(recorded, Mapping):
        raise GateError("manifest.compatibility object required")
    for key, value in compatibility.items():
        require_equal(f"manifest.compatibility.{key}", recorded.get(key), value)
    assessment = assess(profile, data, manifest.get("policy_source"))
    return {
        "schema": "bividi.calibration.camera_imu_evidence_verification.v1",
        "created_utc": utc_now(),
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "calibration_id": manifest.get("calibration_id"),
        "compatibility": compatibility,
        "assessment": assessment,
        "guardrails": [
            "This gate proves evidence integrity/compatibility and policy disposition; it does not independently prove physical calibration accuracy.",
            "Promotion profile requires explicit PASS reports but does not invent numeric thresholds; threshold values remain in the component evidence reports.",
            "A promotion-ready manifest does not replace downstream VIO validation or measured #8 stereo calibration.",
            "camera_a/camera_b topology names are not silently reinterpreted as physical left/right.",
        ],
        "provenance": {"tool": Path(__file__).name, "tool_version": TOOL_VERSION},
    }


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    inputs = {role: getattr(args, role).resolve() for role in INPUT_ROLES}
    loaded: dict[str, dict[str, Any]] = {}
    for role, path in inputs.items():
        data = load_json(path)
        expected = ROLE_SCHEMAS[role]
        if data.get("schema") != expected:
            raise GateError(f"{role}: expected schema {expected!r}; got {data.get('schema')!r}")
        loaded[role] = data

    coverage = loaded["target_coverage"]
    observations_ref = coverage.get("source")
    observations_path, observations = verified_ref(inputs["target_coverage"], observations_ref,
                                                   "target_coverage.source", ROLE_SCHEMAS["target_observations"])
    assert observations is not None
    loaded["target_observations"] = observations
    inputs["target_observations"] = observations_path

    imported = loaded["import_manifest"]
    result_yaml_path, _ = verified_ref(inputs["import_manifest"], imported.get("kalibr_result"),
                                       "import_manifest.kalibr_result")
    solver = loaded["solver_quality"]
    result_text_path, _ = verified_ref(inputs["solver_quality"], nested(solver, "source", "results_imucam_txt"),
                                       "solver_quality.source.results_imucam_txt")

    evidence = [file_record(role, inputs[role], output, ROLE_SCHEMAS[role]) for role in ROLE_SCHEMAS]
    supporting = [
        file_record("kalibr_result_yaml", result_yaml_path, output),
        file_record("kalibr_results_imucam_txt", result_text_path, output),
    ]
    solver_report = imported.get("solver_report")
    if solver_report is not None:
        solver_report_path, _ = verified_ref(inputs["import_manifest"], solver_report, "import_manifest.solver_report")
        supporting.append(file_record("import_solver_report", solver_report_path, output))

    temp_manifest = {
        "schema": MANIFEST_SCHEMA,
        "manifest_id": args.manifest_id or f"{loaded['candidate'].get('calibration_id', 'camera-imu')}-evidence",
        "calibration_id": loaded["candidate"].get("calibration_id"),
        "created_utc": utc_now(),
        "policy_source": args.policy_source,
        "evidence": evidence,
        "supporting_files": supporting,
        "compatibility": {},
        "provenance": {"tool": Path(__file__).name, "tool_version": TOOL_VERSION},
        "guardrails": [
            "Manifest creation freezes file identity; verification re-hashes every bound evidence file.",
            "No component threshold is invented or rewritten by this manifest.",
        ],
    }

    # Resolve the records against the future output location before writing.
    entry_map = evidence_map(temp_manifest)
    bound_paths: dict[str, Path] = {}
    bound_data: dict[str, dict[str, Any]] = {}
    for role, entry in entry_map.items():
        path, data = verify_record(entry, output, expected_schema=ROLE_SCHEMAS[role])
        assert data is not None
        bound_paths[role] = path
        bound_data[role] = data
    support_paths: dict[str, Path] = {}
    for role, entry in support_map(temp_manifest).items():
        path, _ = verify_record(entry, output)
        support_paths[role] = path
    temp_manifest["compatibility"] = verify_nested_links(bound_paths, bound_data, support_paths)
    return temp_manifest


def render_markdown(report: Mapping[str, Any]) -> str:
    assessment = report["assessment"]
    compatibility = report["compatibility"]
    lines = [
        "# Camera↔IMU Calibration Evidence Verification",
        "",
        f"Profile: `{assessment['profile']}`",
        f"Status: **{assessment['status']}**",
        f"Disposition: **{assessment['disposition']}**",
        f"Calibration: `{report.get('calibration_id')}`",
        f"Device serial: `{compatibility.get('device_serial')}`",
        f"Kalibr revision: `{compatibility.get('kalibr_revision')}`",
        f"Camera: `{compatibility.get('camera_id')}` / `{compatibility.get('kalibr_camera')}`",
        f"Camera time semantic: `{compatibility.get('camera_time_reference')}`",
        "",
        "## Evidence status",
        "",
        "| Evidence | Status |",
        "|---|---|",
    ]
    for role, status in assessment["evidence_statuses"].items():
        lines.append(f"| `{role}` | `{status}` |")
    lines += ["", "## Failures", ""]
    if assessment["failures"]:
        lines.extend(f"- {item}" for item in assessment["failures"])
    else:
        lines.append("- None.")
    lines += ["", "## Warnings", ""]
    if assessment["warnings"]:
        lines.extend(f"- {item}" for item in assessment["warnings"])
    else:
        lines.append("- None.")
    lines += ["", "## Guardrails", ""]
    lines.extend(f"- {item}" for item in report["guardrails"])
    return "\n".join(lines) + "\n"


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def make_candidate(path: Path, session_hash: str, *, calibration_id: str, tx: float) -> None:
    data = {
        "schema": ROLE_SCHEMAS["candidate"],
        "calibration_id": calibration_id,
        "created_utc": "2026-09-18T00:00:00Z",
        "device": {"model": "synthetic-rig", "serial": "SYNTHETIC"},
        "camera_reference": {"camera_id": "camera_a", "frame": "camera_a", "width": 1920, "height": 1200,
                             "mode_id": "nori-mode-0-1920x1200-BGR24"},
        "imu_reference": {"model": "synthetic-imu", "frame": "imu", "imu_calibration_id": "imu-synth"},
        "transform": {"from_frame": "imu", "to_frame": "camera_a",
                      "matrix": [[1,0,0,tx],[0,1,0,0],[0,0,1,0],[0,0,0,1]], "translation_unit": "m"},
        "time_offset": {"definition": TIME_OFFSET_DEFINITION, "camera_time_reference": "exposure_midpoint",
                        "offset_s": 0.00025, "method": "synthetic"},
        "frames": {"handedness": "right", "camera_axes": "synthetic-camera-axes", "imu_axes": "synthetic-imu-axes"},
        "provenance": {"kind": "imported", "tool": "synthetic", "source_hash": session_hash,
                       "external_backend": BACKEND, "external_backend_revision": PINNED_KALIBR_REVISION},
    }
    write_json(path, data)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "raw.bin"
        raw.write_bytes(b"raw-source")
        session = root / "session.json"
        write_json(session, {
            "schema": ROLE_SCHEMAS["dynamic_session"], "session_id": "synthetic-session",
            "device": {"serial": "SYNTHETIC"},
            "camera_mapping": {"camera_a": "cam0", "camera_b": "cam1", "guardrail": "synthetic"},
            "camera_time_reference": {"kind": "exposure_midpoint", "time_shift_definition": TIME_OFFSET_DEFINITION},
            "kalibr": {"backend": BACKEND, "revision": PINNED_KALIBR_REVISION},
            "sources": {"synthetic": {"path": str(raw), "sha256": sha256_file(raw)}},
        })
        session_hash = sha256_file(session)
        candidate = root / "candidate.json"
        candidate2 = root / "candidate2.json"
        make_candidate(candidate, session_hash, calibration_id="camimu-001", tx=0.01)
        make_candidate(candidate2, session_hash, calibration_id="camimu-002", tx=0.011)

        result_yaml = root / "result.yaml"
        result_yaml.write_text("synthetic kalibr result yaml\n", encoding="utf-8")
        result_txt = root / "results-imucam.txt"
        result_txt.write_text("synthetic residual report\n", encoding="utf-8")

        observations = root / "target-observations.json"
        write_json(observations, {
            "schema": ROLE_SCHEMAS["target_observations"],
            "session": {"path": str(session), "sha256": session_hash},
            "kalibr": {"backend": BACKEND, "revision": PINNED_KALIBR_REVISION, "reviewed_revision": True},
        })
        coverage = root / "coverage.json"
        write_json(coverage, {
            "schema": ROLE_SCHEMAS["target_coverage"],
            "source": {"path": str(observations), "sha256": sha256_file(observations)},
            "kalibr": {"backend": BACKEND, "revision": PINNED_KALIBR_REVISION, "reviewed_revision": True},
            "assessment": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "thresholds": {}},
        })
        excitation = root / "excitation.json"
        write_json(excitation, {
            "schema": ROLE_SCHEMAS["excitation"],
            "source": {"dynamic_session": {"path": str(session), "sha256": session_hash, "session_id": "synthetic-session"}},
            "session_context": {"kalibr": {"backend": BACKEND, "revision": PINNED_KALIBR_REVISION},
                                "camera_time_reference": {"kind": "exposure_midpoint", "time_shift_definition": TIME_OFFSET_DEFINITION}},
            "assessment": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": []},
        })
        solver = root / "solver.json"
        write_json(solver, {
            "schema": ROLE_SCHEMAS["solver_quality"],
            "source_contract": {"backend": BACKEND, "verified_revision": PINNED_KALIBR_REVISION,
                                "session_revision": PINNED_KALIBR_REVISION, "revision_mismatch_allowed": False},
            "source": {"dynamic_session": {"path": str(session), "sha256": session_hash},
                       "results_imucam_txt": {"path": str(result_txt), "sha256": sha256_file(result_txt)}},
            "assessment": {"status": "EVIDENCE_ONLY_NO_THRESHOLDS", "gates": []},
        })
        import_manifest = root / "import.json"
        write_json(import_manifest, {
            "schema": ROLE_SCHEMAS["import_manifest"], "camera": "cam0", "camera_id": "camera_a",
            "dynamic_session": {"path": str(session), "sha256": session_hash},
            "kalibr_result": {"path": str(result_yaml), "sha256": sha256_file(result_yaml)},
            "solver_report": None, "kalibr_revision": PINNED_KALIBR_REVISION,
            "camera_time_reference": "exposure_midpoint", "time_shift_definition": TIME_OFFSET_DEFINITION,
            "artifact_calibration_id": "camimu-001", "status": "imported_candidate_requires_review",
            "output_artifact": {"path": str(candidate), "sha256": sha256_file(candidate)},
        })
        time_review = root / "time-review.json"
        write_json(time_review, {
            "schema": ROLE_SCHEMAS["time_review"], "status": "EVIDENCE_ONLY_NO_THRESHOLDS",
            "dynamic_session": {"path": str(session), "sha256": session_hash},
            "camera_imu_artifact": {"path": str(candidate), "sha256": sha256_file(candidate)},
            "camera_time_reference": "exposure_midpoint",
            "time_offset": {"definition": TIME_OFFSET_DEFINITION, "kalibr_offset_s": 0.00025},
            "gates": [],
        })
        contract = camera_compatibility_key(load_json(candidate))
        repeat = root / "repeat.json"
        write_json(repeat, {
            "schema": ROLE_SCHEMAS["repeatability"], "status": "EVIDENCE_ONLY_NO_THRESHOLDS",
            "run_count": 2, "compatibility_contract": {**contract, "backend_revisions": [PINNED_KALIBR_REVISION, PINNED_KALIBR_REVISION]},
            "artifacts": [
                {"path": str(candidate), "sha256": sha256_file(candidate), "calibration_id": "camimu-001"},
                {"path": str(candidate2), "sha256": sha256_file(candidate2), "calibration_id": "camimu-002"},
            ],
            "gates": [],
        })

        output = root / "manifest.json"
        args = argparse.Namespace(
            output=output, manifest_id=None, policy_source="synthetic self-test policy",
            dynamic_session=session, excitation=excitation, target_coverage=coverage, solver_quality=solver,
            import_manifest=import_manifest, candidate=candidate, time_review=time_review, repeatability=repeat,
        )
        manifest = build_manifest(args)
        write_json(output, manifest)
        integrity = verify_manifest(output, "integrity")
        assert integrity["assessment"]["disposition"] == "INTEGRITY_VERIFIED"
        review = verify_manifest(output, "review")
        assert review["assessment"]["disposition"] == "REVIEW_READY"
        promotion = verify_manifest(output, "promotion")
        assert promotion["assessment"]["status"] == "FAIL"
        assert any("explicit PASS" in item for item in promotion["assessment"]["failures"])

        original_excitation = excitation.read_text(encoding="utf-8")
        excitation.write_text(original_excitation + " ", encoding="utf-8")
        try:
            verify_manifest(output, "integrity")
        except GateError:
            pass
        else:
            raise AssertionError("tampered evidence hash was not rejected")
        excitation.write_text(original_excitation, encoding="utf-8")

        # Rebuild with explicit passing evidence to exercise the promotion profile.
        exc = load_json(excitation)
        exc["assessment"] = {"status": "PASS", "gates": [{"name": "synthetic", "status": "PASS"}]}
        write_json(excitation, exc)
        cov = load_json(coverage)
        cov["assessment"] = {"status": "PASS", "thresholds": {"synthetic": 0.5}, "failed_gates": []}
        write_json(coverage, cov)
        sol = load_json(solver)
        sol["assessment"] = {"status": "PASS", "gates": [{"name": "synthetic", "status": "PASS"}]}
        write_json(solver, sol)
        tr = load_json(time_review)
        tr["status"] = "PASS"
        tr["gates"] = [{"name": "synthetic", "passed": True}]
        write_json(time_review, tr)
        rp = load_json(repeat)
        rp["status"] = "PASS"
        rp["gates"] = [{"name": "synthetic", "passed": True}]
        write_json(repeat, rp)

        promoted_output = root / "manifest-promoted.json"
        args.output = promoted_output
        promoted_manifest = build_manifest(args)
        write_json(promoted_output, promoted_manifest)
        promoted = verify_manifest(promoted_output, "promotion")
        assert promoted["assessment"]["disposition"] == "PROMOTION_READY"

    print("Camera-IMU calibration evidence promotion gate self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create", help="create a hash-bound evidence manifest")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--manifest-id")
    create.add_argument("--policy-source")
    for role in INPUT_ROLES:
        create.add_argument("--" + role.replace("_", "-"), dest=role, type=Path, required=True)

    verify = sub.add_parser("verify", help="re-hash and evaluate an evidence manifest")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--profile", choices=("integrity", "review", "promotion"), default="review")
    verify.add_argument("--output-prefix", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.command == "create":
        try:
            manifest = build_manifest(args)
            write_json(args.output.resolve(), manifest)
            report = verify_manifest(args.output.resolve(), "integrity")
        except (GateError, OSError) as exc:
            print(f"camera-IMU evidence manifest creation failed: {exc}", file=sys.stderr)
            return 3
        print(json.dumps({
            "manifest": str(args.output.resolve()),
            "sha256": sha256_file(args.output.resolve()),
            "status": report["assessment"]["status"],
            "disposition": report["assessment"]["disposition"],
        }, indent=2))
        return 0
    if args.command == "verify":
        try:
            manifest_path = args.manifest.resolve()
            report = verify_manifest(manifest_path, args.profile)
            if args.output_prefix is not None:
                prefix = args.output_prefix.resolve()
                write_json(Path(str(prefix) + ".verification.json"), report)
                Path(str(prefix) + ".verification.md").write_text(render_markdown(report), encoding="utf-8")
        except (GateError, OSError) as exc:
            print(f"camera-IMU evidence verification failed: {exc}", file=sys.stderr)
            return 3
        print(json.dumps({
            "profile": report["assessment"]["profile"],
            "status": report["assessment"]["status"],
            "disposition": report["assessment"]["disposition"],
            "failures": report["assessment"]["failures"],
            "warnings": report["assessment"]["warnings"],
        }, indent=2))
        return 4 if report["assessment"]["status"] == "FAIL" else 0
    parser.error("choose create or verify, or use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
