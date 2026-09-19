"""Validate the versioned Bividi VIO backend evaluation/adoption-gate artifact."""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "bividi.vio.backend_evaluation.v1"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WINDOWS_STATES = {"verified", "unsupported", "unverified"}
PLATFORM_STATES = WINDOWS_STATES | {"partial"}
DISPOSITIONS = {"spike_candidate", "shortlist", "reference_only", "deferred"}
ADOPTION_STATES = {"NOT_ADOPTED", "ADOPTED"}
GATE_STATES = {"OPEN", "PASS", "BLOCKED_ON_HARDWARE", "BLOCKED"}
REQUIRED_ADOPTION_GATES = (
    "license_distribution_decision",
    "calibration_mapping_8_47",
    "timestamp_reset_mapping_135",
    "backend_adapter_conformance",
    "pinned_linux_build_offline_run",
    "windows_feasibility",
    "cpu_init_recovery_rate_characterization",
    "measured_ar0234_35_8_47",
)


class EvaluationError(ValueError):
    pass


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def validate(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, Mapping):
        return ["artifact root must be an object"]
    if document.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not _nonempty(document.get("review_id")):
        errors.append("review_id must be non-empty")
    if not isinstance(document.get("review_date"), str) or not DATE_RE.fullmatch(document["review_date"]):
        errors.append("review_date must be YYYY-MM-DD")

    context = _mapping(document.get("project_license_context"))
    if context is None:
        errors.append("project_license_context must be an object")
        copyleft_decision = None
    else:
        if not isinstance(context.get("bividi_repository_license_declared"), bool):
            errors.append("project_license_context.bividi_repository_license_declared must be boolean")
        copyleft_decision = context.get("copyleft_integration_decision")
        if copyleft_decision not in {"not_made", "accepted", "rejected"}:
            errors.append("project_license_context.copyleft_integration_decision invalid")

    gates = _mapping(document.get("adoption_gates"))
    if gates is None:
        errors.append("adoption_gates must be an object")
        gates = {}
    else:
        if set(gates) != set(REQUIRED_ADOPTION_GATES):
            missing = sorted(set(REQUIRED_ADOPTION_GATES) - set(gates))
            extra = sorted(set(gates) - set(REQUIRED_ADOPTION_GATES))
            if missing:
                errors.append("missing adoption gates: " + ", ".join(missing))
            if extra:
                errors.append("unknown adoption gates: " + ", ".join(extra))
        for name, state in gates.items():
            if state not in GATE_STATES:
                errors.append(f"adoption_gates.{name} has invalid state {state!r}")

    candidates = document.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        errors.append("candidates must contain at least two entries")
        candidates = []

    ids: set[str] = set()
    spike_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        prefix = f"candidates[{index}]"
        if not isinstance(candidate, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        candidate_id = candidate.get("id")
        if not _nonempty(candidate_id):
            errors.append(f"{prefix}.id must be non-empty")
        elif candidate_id in ids:
            errors.append(f"duplicate candidate id: {candidate_id}")
        else:
            ids.add(candidate_id)

        repository = candidate.get("repository")
        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            errors.append(f"{prefix}.repository must be owner/name")
        revision = candidate.get("revision")
        if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
            errors.append(f"{prefix}.revision must be an exact lowercase 40-hex commit")
        if not isinstance(candidate.get("revision_date"), str) or not DATE_RE.fullmatch(candidate["revision_date"]):
            errors.append(f"{prefix}.revision_date must be YYYY-MM-DD")
        if not _nonempty(candidate.get("source_kind")):
            errors.append(f"{prefix}.source_kind must be non-empty")

        license_info = _mapping(candidate.get("license"))
        license_class = None
        if license_info is None:
            errors.append(f"{prefix}.license must be an object")
        else:
            if not _nonempty(license_info.get("spdx")) or str(license_info.get("spdx")).lower() == "unknown":
                errors.append(f"{prefix}.license.spdx must be explicit")
            license_class = license_info.get("class")
            if license_class not in {"permissive", "strong-copyleft", "other"}:
                errors.append(f"{prefix}.license.class invalid")
            if license_info.get("third_party_license_review") not in {"required", "reviewed"}:
                errors.append(f"{prefix}.license.third_party_license_review invalid")

        build = _mapping(candidate.get("build"))
        if build is None:
            errors.append(f"{prefix}.build must be an object")
        else:
            if not _nonempty(build.get("cpp_standard")):
                errors.append(f"{prefix}.build.cpp_standard must be explicit")
            dependencies = build.get("major_dependencies")
            if not isinstance(dependencies, list) or not dependencies or not all(_nonempty(item) for item in dependencies):
                errors.append(f"{prefix}.build.major_dependencies must be a non-empty string array")
            for platform in ("linux", "windows", "macos"):
                platform_info = _mapping(build.get(platform))
                if platform_info is None:
                    errors.append(f"{prefix}.build.{platform} must be an object")
                    continue
                allowed = WINDOWS_STATES if platform == "windows" else PLATFORM_STATES
                if platform_info.get("status") not in allowed:
                    errors.append(f"{prefix}.build.{platform}.status invalid")
                if not _nonempty(platform_info.get("basis")):
                    errors.append(f"{prefix}.build.{platform}.basis must be explicit")

        capabilities = _mapping(candidate.get("capabilities"))
        if capabilities is None:
            errors.append(f"{prefix}.capabilities must be an object")
        else:
            for field in ("stereo_imu", "ros_free_library"):
                if capabilities.get(field) not in {"documented", "not_documented", "unverified"}:
                    errors.append(f"{prefix}.capabilities.{field} invalid")
            models = capabilities.get("camera_models")
            if not isinstance(models, list) or not models or not all(_nonempty(item) for item in models):
                errors.append(f"{prefix}.capabilities.camera_models must be a non-empty string array")

        integration = _mapping(candidate.get("integration"))
        if integration is None:
            errors.append(f"{prefix}.integration must be an object")
        else:
            for field in ("reset_reinitialize_api", "tracking_state_api", "timestamp_mapping", "bividi_calibration_mapping", "cpu_runtime"):
                if not _nonempty(integration.get(field)):
                    errors.append(f"{prefix}.integration.{field} must be explicit")

        disposition = candidate.get("disposition")
        if disposition not in DISPOSITIONS:
            errors.append(f"{prefix}.disposition invalid")
        if disposition == "spike_candidate" and _nonempty(candidate_id):
            spike_ids.append(candidate_id)
        if license_class == "strong-copyleft" and copyleft_decision != "accepted" and disposition != "reference_only":
            errors.append(f"{prefix}: strong-copyleft candidate must remain reference_only until copyleft decision is accepted")

        blockers = candidate.get("blockers")
        if not isinstance(blockers, list) or not blockers or not all(_nonempty(item) for item in blockers):
            errors.append(f"{prefix}.blockers must be a non-empty string array")

        evidence = candidate.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{prefix}.evidence must be non-empty")
        else:
            for evidence_index, entry in enumerate(evidence):
                ep = f"{prefix}.evidence[{evidence_index}]"
                if not isinstance(entry, Mapping):
                    errors.append(f"{ep} must be an object")
                    continue
                url = entry.get("url")
                if not _nonempty(url):
                    errors.append(f"{ep}.url must be non-empty")
                elif isinstance(revision, str) and REVISION_RE.fullmatch(revision) and revision not in url:
                    errors.append(f"{ep}.url must be pinned to candidate revision")
                claims = entry.get("claims")
                if not isinstance(claims, list) or not claims or not all(_nonempty(item) for item in claims):
                    errors.append(f"{ep}.claims must be a non-empty string array")

    if len(spike_ids) > 1:
        errors.append("at most one candidate may be disposition=spike_candidate")

    decision = _mapping(document.get("decision"))
    if decision is None:
        errors.append("decision must be an object")
    else:
        adoption_status = decision.get("adoption_status")
        if adoption_status not in ADOPTION_STATES:
            errors.append("decision.adoption_status invalid")
        spike_candidate = decision.get("spike_candidate")
        if spike_candidate is not None and spike_candidate not in ids:
            errors.append("decision.spike_candidate must name a candidate")
        if spike_ids:
            if spike_candidate != spike_ids[0]:
                errors.append("decision.spike_candidate must match the sole spike_candidate disposition")
        elif spike_candidate is not None:
            errors.append("decision.spike_candidate set but no candidate has spike_candidate disposition")

        selected = decision.get("selected_backend")
        if adoption_status == "NOT_ADOPTED" and selected is not None:
            errors.append("NOT_ADOPTED decision cannot name selected_backend")
        if adoption_status == "ADOPTED":
            if selected not in ids:
                errors.append("ADOPTED decision requires selected_backend candidate")
            incomplete = [name for name in REQUIRED_ADOPTION_GATES if gates.get(name) != "PASS"]
            if incomplete:
                errors.append("ADOPTED decision requires all adoption gates PASS: " + ", ".join(incomplete))

    guardrails = document.get("guardrails")
    if not isinstance(guardrails, list) or not guardrails or not all(_nonempty(item) for item in guardrails):
        errors.append("guardrails must be a non-empty string array")
    return errors


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationError("artifact root must be an object")
    return value


def _minimal_valid() -> dict[str, Any]:
    candidate = {
        "id": "candidate-a",
        "repository": "org/repo",
        "source_kind": "upstream-github",
        "revision": "a" * 40,
        "revision_date": "2026-09-19",
        "license": {"spdx": "BSD-2-Clause", "class": "permissive", "third_party_license_review": "required"},
        "capabilities": {"stereo_imu": "documented", "ros_free_library": "documented", "camera_models": ["pinhole"]},
        "build": {
            "cpp_standard": "C++17",
            "major_dependencies": ["Eigen3"],
            "linux": {"status": "verified", "basis": "CI"},
            "windows": {"status": "unverified", "basis": "not measured"},
            "macos": {"status": "unverified", "basis": "not measured"}
        },
        "integration": {
            "reset_reinitialize_api": "unreviewed",
            "tracking_state_api": "unreviewed",
            "timestamp_mapping": "unreviewed",
            "bividi_calibration_mapping": "unreviewed",
            "cpu_runtime": "unreviewed"
        },
        "disposition": "spike_candidate",
        "blockers": ["not integrated"],
        "evidence": [{"url": "https://github.com/org/repo/blob/" + "a" * 40 + "/README.md", "claims": ["fixture"]}]
    }
    other = copy.deepcopy(candidate)
    other["id"] = "candidate-b"
    other["repository"] = "org/other"
    other["revision"] = "b" * 40
    other["disposition"] = "shortlist"
    other["evidence"][0]["url"] = "https://github.com/org/other/blob/" + "b" * 40 + "/README.md"
    return {
        "schema": SCHEMA,
        "review_id": "fixture",
        "review_date": "2026-09-19",
        "bividi_boundary": {"parent_issue": 46},
        "project_license_context": {
            "bividi_repository_license_declared": False,
            "copyleft_integration_decision": "not_made",
            "note": "fixture"
        },
        "decision": {
            "adoption_status": "NOT_ADOPTED",
            "selected_backend": None,
            "spike_candidate": "candidate-a",
            "spike_scope": "fixture",
            "rationale": ["fixture"]
        },
        "adoption_gates": {name: "OPEN" for name in REQUIRED_ADOPTION_GATES},
        "candidates": [candidate, other],
        "guardrails": ["fixture"]
    }


def self_test() -> None:
    valid = _minimal_valid()
    assert not validate(valid), validate(valid)

    mutation = copy.deepcopy(valid)
    mutation["candidates"][0]["revision"] = "master"
    assert any("40-hex" in item for item in validate(mutation))

    mutation = copy.deepcopy(valid)
    mutation["candidates"][0]["build"]["windows"]["status"] = "probably"
    assert any("windows.status" in item for item in validate(mutation))

    mutation = copy.deepcopy(valid)
    mutation["candidates"][0]["evidence"] = []
    assert any("evidence" in item for item in validate(mutation))

    mutation = copy.deepcopy(valid)
    mutation["decision"]["adoption_status"] = "ADOPTED"
    mutation["decision"]["selected_backend"] = "candidate-a"
    assert any("all adoption gates PASS" in item for item in validate(mutation))

    mutation = copy.deepcopy(valid)
    mutation["candidates"][1]["license"]["class"] = "strong-copyleft"
    mutation["candidates"][1]["license"]["spdx"] = "GPL-3.0"
    mutation["candidates"][1]["disposition"] = "shortlist"
    assert any("strong-copyleft" in item for item in validate(mutation))

    mutation = copy.deepcopy(valid)
    mutation["decision"]["adoption_status"] = "ADOPTED"
    mutation["decision"]["selected_backend"] = "candidate-a"
    mutation["adoption_gates"] = {name: "PASS" for name in REQUIRED_ADOPTION_GATES}
    assert not validate(mutation), validate(mutation)
    print("VIO backend evaluation validator self-test: PASS")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", nargs="?", type=Path, default=Path("vio/backend-evaluation-v1.json"))
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(argv)
    if parsed.self_test:
        self_test()
        return 0
    try:
        document = load(parsed.artifact)
    except EvaluationError as exc:
        print(f"vio-backend-evaluation: error: {exc}", file=sys.stderr)
        return 2
    errors = validate(document)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"VIO backend evaluation artifact: VALID ({len(document['candidates'])} candidates; {document['decision']['adoption_status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
