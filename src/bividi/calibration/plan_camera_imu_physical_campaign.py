#!/usr/bin/env python3
"""Plan and audit a physical camera↔IMU calibration campaign.

This tool does not acquire hardware, solve calibration, or invent acceptance limits.
It creates a deterministic campaign manifest + human runbook that wires together
Bividi's #47 evidence tools, then audits whether the expected artifacts exist and
match their declared schemas.

The planner is intentionally dependency-free so it can run in normal CI. External
Kalibr execution remains a separate laboratory step.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "bividi.calibration.camera_imu_physical_campaign.v1"
TOOL_VERSION = "1"
PINNED_KALIBR_REVISION = "1f60227442d25e36365ef5f72cd80b9666d73467"
TIME_OFFSET_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"
CAMERA_TIME_REFERENCES = ("exposure_start", "exposure_midpoint", "exposure_end")


class CampaignError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def rel(path: Path, root: Path) -> str:
    return os.path.relpath(path.resolve(), root.resolve()).replace(os.sep, "/")


def artifact(path: str, schema: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path}
    if schema is not None:
        result["schema"] = schema
    return result


def stage(stage_id: str, title: str, outputs: list[dict[str, Any]], *,
          depends_on: Sequence[str] = (), runtime: str = "bividi",
          evidence_class: str, notes: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "id": stage_id,
        "title": title,
        "depends_on": list(depends_on),
        "runtime": runtime,
        "evidence_class": evidence_class,
        "outputs": outputs,
        "notes": list(notes),
    }


def build_stages(dynamic_count: int) -> list[dict[str, Any]]:
    if dynamic_count < 2:
        raise CampaignError("--dynamic-session-count must be >= 2 because repeatability needs independent solves")

    stages: list[dict[str, Any]] = [
        stage(
            "capture_stationary_short",
            "Short stationary IMU capture for bias/cadence sanity",
            [artifact("imu/stationary-short.imu.csv")],
            evidence_class="measured_raw",
            notes=["Keep the rig mechanically stationary.", "Do not infer sensor full-scale from vendor demo constants."],
        ),
        stage(
            "audit_stationary_timing",
            "Protocol-level device timestamp/cadence audit",
            [artifact("imu/stationary-short.timing.json", "bividi.calibration.camera_imu_timing_audit.v1")],
            depends_on=("capture_stationary_short",),
            evidence_class="timing",
            notes=["This is device-time evidence; nearest-sample geometry is not a calibrated camera↔IMU offset."],
        ),
        stage(
            "analyze_stationary",
            "Stationary IMU statistics",
            [artifact("imu/stationary-short.stationary.json", "bividi.calibration.imu_stationary_analysis.v1")],
            depends_on=("capture_stationary_short",),
            evidence_class="derived",
        ),
        stage(
            "capture_allan",
            "Long stationary IMU capture for Allan/noise analysis",
            [artifact("imu/allan-long.imu.csv")],
            evidence_class="measured_raw",
            notes=["Duration is experiment-owned; this planner does not invent a universal number of hours."],
        ),
        stage(
            "analyze_allan",
            "Allan/noise evidence",
            [artifact("imu/allan-long.allan.json", "bividi.calibration.imu_allan_analysis.v1")],
            depends_on=("capture_allan",),
            evidence_class="derived",
            notes=["Fit windows and 3-axis reduction policy must be explicitly justified."],
        ),
        stage(
            "capture_six_position",
            "Six-position accelerometer campaign",
            [artifact("imu/six-position.manifest.json")],
            evidence_class="measured_raw",
        ),
        stage(
            "analyze_six_position",
            "Accelerometer axis/sign/scale evidence",
            [artifact("imu/six-position.analysis.json", "bividi.calibration.imu_six_position_analysis.v1")],
            depends_on=("capture_six_position",),
            evidence_class="derived",
        ),
        stage(
            "capture_gyro_rotation",
            "Controlled +/-XYZ gyroscope rotation campaign",
            [artifact("imu/gyro-rotation.manifest.json")],
            evidence_class="measured_raw",
        ),
        stage(
            "analyze_gyro_rotation",
            "Gyroscope axis/sign/scale evidence",
            [artifact("imu/gyro-rotation.analysis.json", "bividi.calibration.imu_gyro_rotation_analysis.v1")],
            depends_on=("capture_gyro_rotation",),
            evidence_class="derived",
        ),
        stage(
            "imu_provenance",
            "Bind compatible IMU evidence into one session",
            [artifact("imu/imu-session.json", "bividi.calibration.imu_session_manifest.v1")],
            depends_on=(
                "audit_stationary_timing", "analyze_stationary", "analyze_allan",
                "analyze_six_position", "analyze_gyro_rotation",
            ),
            evidence_class="provenance",
        ),
        stage(
            "imu_config_consistency",
            "Declared-vs-measured IMU configuration consistency",
            [artifact("imu/imu-config-consistency.json", "bividi.calibration.imu_config_consistency.v1")],
            depends_on=("imu_provenance",),
            evidence_class="quality",
            notes=["This compares measured response against declared range/ODR; it is not register readback."],
        ),
        stage(
            "imu_promote",
            "Review/promote measured IMU artifact",
            [artifact("imu/imu-calibration.json", "bividi.calibration.imu.v1")],
            depends_on=("imu_config_consistency",),
            evidence_class="promoted_candidate",
            notes=["Promotion remains a review decision; this planner never manufactures values."],
        ),
    ]

    repeat_inputs: list[str] = []
    for index in range(1, dynamic_count + 1):
        sid = f"dynamic_{index:02d}"
        prefix = f"dynamic/session-{index:02d}"
        stages.extend([
            stage(
                f"{sid}_capture",
                f"Dynamic stereo+IMU AprilGrid capture #{index}",
                [artifact(f"{prefix}/capture.json", "bividi.nori.camera_imu_dynamic_trace.v1")],
                depends_on=("imu_promote",),
                evidence_class="measured_raw",
                notes=["Use stable #35 acquisition and the measured #8 camera chain for this specimen/mode."],
            ),
            stage(
                f"{sid}_prepare",
                f"Prepare Kalibr session #{index}",
                [artifact(f"{prefix}/kalibr/session.json", "bividi.calibration.kalibr_dynamic_session.v1")],
                depends_on=(f"{sid}_capture",),
                evidence_class="adapter",
            ),
            stage(
                f"{sid}_excitation",
                f"Dynamic excitation evidence #{index}",
                [artifact(f"{prefix}/excitation.json", "bividi.calibration.camera_imu_excitation.v1")],
                depends_on=(f"{sid}_prepare",),
                evidence_class="quality",
            ),
            stage(
                f"{sid}_target_observations",
                f"Exact Kalibr AprilGrid observations #{index}",
                [artifact(f"{prefix}/target.target-observations.json", "bividi.calibration.kalibr_target_observations.v1")],
                depends_on=(f"{sid}_prepare",),
                runtime="external_kalibr",
                evidence_class="quality_source",
            ),
            stage(
                f"{sid}_target_coverage",
                f"AprilGrid image-plane/target coverage #{index}",
                [artifact(f"{prefix}/target-coverage.json", "bividi.calibration.kalibr_target_coverage.v1")],
                depends_on=(f"{sid}_target_observations",),
                evidence_class="quality",
            ),
            stage(
                f"{sid}_solve",
                f"External Kalibr camera↔IMU solve #{index}",
                [
                    artifact(f"{prefix}/kalibr/result-camchain-imucam.yaml"),
                    artifact(f"{prefix}/kalibr/results-imucam.txt"),
                ],
                depends_on=(f"{sid}_prepare", f"{sid}_excitation", f"{sid}_target_coverage"),
                runtime="external_kalibr",
                evidence_class="external_solver",
                notes=["Keep exact solver revision/container provenance."],
            ),
            stage(
                f"{sid}_solver_quality",
                f"Kalibr solver residual quality #{index}",
                [artifact(f"{prefix}/solver-quality.json", "bividi.calibration.kalibr_solver_quality.v1")],
                depends_on=(f"{sid}_solve",),
                evidence_class="quality",
            ),
            stage(
                f"{sid}_import",
                f"Import T_cam_imu + timeshift #{index}",
                [
                    artifact(f"{prefix}/camera-imu.json", "bividi.calibration.camera_imu.v1"),
                    artifact(f"{prefix}/camera-imu.import.json", "bividi.calibration.kalibr_camera_imu_import.v1"),
                ],
                depends_on=(f"{sid}_solve",),
                evidence_class="candidate",
            ),
            stage(
                f"{sid}_time_review",
                f"Device-time temporal evidence review #{index}",
                [artifact(f"{prefix}/time-review.json", "bividi.calibration.camera_imu_time_review.v1")],
                depends_on=(f"{sid}_import",),
                evidence_class="quality",
            ),
        ])
        repeat_inputs.append(f"{sid}_import")

    stages.extend([
        stage(
            "repeatability",
            "Cross-session spatial/temporal repeatability",
            [artifact("final/repeatability.json", "bividi.calibration.camera_imu_repeatability.v1")],
            depends_on=tuple(repeat_inputs),
            evidence_class="quality",
        ),
        stage(
            "final_promotion",
            "Final camera↔IMU evidence promotion boundary",
            [artifact("final/camera-imu-evidence.json", "bividi.calibration.camera_imu_evidence_manifest.v1")],
            depends_on=("repeatability",),
            evidence_class="promotion",
            notes=[
                "Run tools/camera_imu_calibration_provenance.py with profile=promotion only after explicit quality gates PASS.",
                "PROMOTION_READY is a policy/evidence disposition, not proof of physical calibration accuracy.",
            ],
        ),
    ])
    return stages


def make_manifest(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "campaign_id": args.campaign_id,
        "created_utc": utc_now(),
        "specimen": {"model": args.model, "serial": args.serial},
        "capture": {
            "device_index": args.device,
            "mode_index": args.mode,
            "camera_time_reference": args.camera_time_reference,
            "time_offset_definition": TIME_OFFSET_DEFINITION,
        },
        "dependencies": {
            "host_acquisition_issue": 35,
            "stereo_calibration_issue": 8,
            "camera_imu_issue": 47,
            "downstream_vio_issue": 46,
            "kalibr_backend": "ethz-asl/kalibr",
            "kalibr_revision": PINNED_KALIBR_REVISION,
        },
        "dynamic_session_count": args.dynamic_session_count,
        "policy_source": args.policy_source,
        "root": ".",
        "stages": build_stages(args.dynamic_session_count),
        "guardrails": [
            "No numeric acceptance limit is invented by this campaign planner.",
            "Physical camera A/B -> left/right identity remains evidence-owned by #35.",
            "Vendor synchronization claims do not replace measured temporal evidence.",
            "Kalibr/ROS stay outside Bividi Core.",
            "#46 accuracy claims remain blocked until measured #8 + #47 calibration is frozen.",
        ],
        "provenance": {"tool": Path(__file__).name, "tool_version": TOOL_VERSION},
    }


def render_runbook(manifest: dict[str, Any]) -> str:
    specimen = manifest["specimen"]
    capture = manifest["capture"]
    lines = [
        f"# Camera↔IMU Physical Calibration Campaign — {manifest['campaign_id']}",
        "",
        f"Specimen: `{specimen['model']}` / `{specimen['serial']}`  ",
        f"Nori device/mode: `{capture['device_index']}` / `{capture['mode_index']}`  ",
        f"Camera timestamp semantic: `{capture['camera_time_reference']}`  ",
        f"Kalibr revision: `{manifest['dependencies']['kalibr_revision']}`",
        "",
        "## Execution rule",
        "",
        "Tools first, measurements second, promotion last. Do not skip an evidence class because a solver returned numbers.",
        "",
        "## Stages",
        "",
    ]
    for idx, st in enumerate(manifest["stages"], start=1):
        deps = ", ".join(st["depends_on"]) if st["depends_on"] else "none"
        outputs = ", ".join(item["path"] for item in st["outputs"])
        lines.extend([
            f"### {idx}. `{st['id']}` — {st['title']}",
            "",
            f"Runtime: `{st['runtime']}`  ",
            f"Evidence class: `{st['evidence_class']}`  ",
            f"Depends on: `{deps}`  ",
            f"Expected output(s): `{outputs}`",
            "",
        ])
        for note in st.get("notes", []):
            lines.append(f"- {note}")
        if st.get("notes"):
            lines.append("")
    lines.extend([
        "## Final review",
        "",
        "Before `promotion`, verify exact specimen/config provenance, protocol timing, declared-vs-measured IMU configuration, all hashes, target coverage, motion excitation, solver fit, device-time review, and independent-session repeatability. Numeric quality limits must come from an explicit lab/product policy source, not this planner.",
        "",
    ])
    return "\n".join(lines)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"cannot read campaign manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise CampaignError(f"{path}: expected schema {SCHEMA!r}")
    return data


def audit(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    data = load_manifest(manifest_path)
    root = manifest_path.parent
    stage_state: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    for st in data.get("stages", []):
        if not isinstance(st, dict) or not isinstance(st.get("id"), str):
            raise CampaignError("campaign contains invalid stage")
        deps = st.get("depends_on", [])
        deps_complete = all(stage_state.get(dep) == "complete" for dep in deps)
        outputs = st.get("outputs", [])
        output_details = []
        all_present = True
        all_valid = True
        for item in outputs:
            path = root / item["path"]
            present = path.is_file()
            schema_ok: bool | None = None
            if not present:
                all_present = False
                all_valid = False
            elif isinstance(item.get("schema"), str):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    schema_ok = isinstance(payload, dict) and payload.get("schema") == item["schema"]
                except (OSError, json.JSONDecodeError):
                    schema_ok = False
                if not schema_ok:
                    all_valid = False
            output_details.append({"path": item["path"], "present": present, "schema_ok": schema_ok})
        if all_present and all_valid:
            state = "complete"
        elif deps_complete:
            state = "ready"
        else:
            state = "blocked"
        stage_state[st["id"]] = state
        details.append({"id": st["id"], "state": state, "outputs": output_details})
    complete = sum(1 for state in stage_state.values() if state == "complete")
    return {
        "schema": "bividi.calibration.camera_imu_physical_campaign_audit.v1",
        "campaign_id": data.get("campaign_id"),
        "manifest": rel(manifest_path, root),
        "summary": {
            "stages": len(stage_state),
            "complete": complete,
            "ready": sum(1 for state in stage_state.values() if state == "ready"),
            "blocked": sum(1 for state in stage_state.values() if state == "blocked"),
            "complete_fraction": complete / len(stage_state) if stage_state else 0.0,
        },
        "stages": details,
        "promotion_artifact_present": stage_state.get("final_promotion") == "complete",
        "note": "Artifact presence/schema audit only; it does not replace evidence-tool verification or promotion policy checks.",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "campaign"
        args = argparse.Namespace(
            campaign_id="synthetic-campaign", model="SYNTHETIC", serial="SYNTHETIC-001",
            device=0, mode=0, camera_time_reference="exposure_midpoint",
            dynamic_session_count=2, policy_source=None,
        )
        root.mkdir(parents=True)
        manifest = make_manifest(args, root)
        stage_ids = [st["id"] for st in manifest["stages"]]
        assert "audit_stationary_timing" in stage_ids
        assert "imu_config_consistency" in stage_ids
        assert stage_ids.index("imu_config_consistency") < stage_ids.index("imu_promote")
        manifest_path = root / "campaign.json"
        write_json(manifest_path, manifest)
        (root / "RUNBOOK.md").write_text(render_runbook(manifest), encoding="utf-8")
        first_audit = audit(manifest_path)
        assert first_audit["summary"]["complete"] == 0
        assert first_audit["summary"]["ready"] >= 1
        first_output = manifest["stages"][0]["outputs"][0]["path"]
        path = root / first_output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic\n", encoding="utf-8")
        second_audit = audit(manifest_path)
        assert second_audit["stages"][0]["state"] == "complete"
        assert second_audit["summary"]["complete"] == 1
        try:
            build_stages(1)
            raise AssertionError("dynamic_session_count=1 must fail")
        except CampaignError:
            pass
    print("Camera-IMU physical campaign planner self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="create a physical campaign directory")
    init.add_argument("root", type=Path)
    init.add_argument("--campaign-id", required=True)
    init.add_argument("--model", required=True)
    init.add_argument("--serial", required=True)
    init.add_argument("--device", type=int, required=True)
    init.add_argument("--mode", type=int, required=True)
    init.add_argument("--camera-time-reference", choices=CAMERA_TIME_REFERENCES, required=True)
    init.add_argument("--dynamic-session-count", type=int, required=True)
    init.add_argument("--policy-source")

    check = sub.add_parser("audit", help="audit expected campaign artifacts")
    check.add_argument("manifest", type=Path)
    check.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.command == "init":
        root = args.root.resolve()
        if root.exists() and any(root.iterdir()):
            raise CampaignError(f"campaign root is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        manifest = make_manifest(args, root)
        write_json(root / "campaign.json", manifest)
        (root / "RUNBOOK.md").write_text(render_runbook(manifest), encoding="utf-8")
        print(root / "campaign.json")
        print(root / "RUNBOOK.md")
        return 0
    if args.command == "audit":
        report = audit(args.manifest)
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    raise CampaignError("choose init or audit, or use --self-test")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CampaignError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2)
