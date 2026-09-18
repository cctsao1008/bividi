"""Plan and audit a physical stereo-calibration campaign for Bividi issue #8.

The planner wires together target scale, session capture, dataset inspection,
native solve, physical baseline review, rectification evidence, independent-session
repeatability, optional Kalibr cross-check, and final promotion. It never invents
numeric calibration thresholds.

This is the installed implementation for the legacy
``tools/plan_stereo_calibration_campaign.py`` compatibility entry point.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "bividi.calibration.stereo_physical_campaign.v1"
AUDIT_SCHEMA = "bividi.calibration.stereo_physical_campaign_audit.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "plan_stereo_calibration_campaign.py"


class CampaignError(ValueError):
    pass


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def artifact(path: str, schema: str | None = None, required: bool = True) -> dict[str, Any]:
    value: dict[str, Any] = {"path": path, "required": required}
    if schema:
        value["schema"] = schema
    return value


def stage(
    stage_id: str,
    title: str,
    outputs: list[dict[str, Any]],
    depends: Sequence[str] = (),
    runtime: str = "bividi",
    kind: str = "evidence",
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "title": title,
        "depends_on": list(depends),
        "runtime": runtime,
        "evidence_class": kind,
        "outputs": outputs,
        "notes": list(notes),
    }


def build_stages(count: int) -> list[dict[str, Any]]:
    if count < 2:
        raise CampaignError(
            "--session-count must be >= 2 because repeatability requires independent solves"
        )

    stages = [
        stage(
            "target_definition",
            "Create versioned physical calibration target",
            [artifact("target/target.json", "bividi.calibration.stereo_target.v1")],
            kind="definition",
            notes=[
                "Native path uses ChArUco; AprilGrid metadata remains available for optional Kalibr interoperability."
            ],
        ),
        stage(
            "target_scale",
            "Physically verify printed target scale",
            [
                artifact(
                    "target/target-scale.json",
                    "bividi.calibration.stereo_target_scale_review.v1",
                )
            ],
            depends=("target_definition",),
            kind="quality",
            notes=[
                "Measure the printed board physically; printer settings are not scale proof."
            ],
        ),
    ]

    repeatability_dependencies: list[str] = []
    for number in range(1, count + 1):
        session_id = f"session_{number:02d}"
        root = f"sessions/session-{number:02d}"
        stages += [
            stage(
                f"{session_id}_capture",
                f"Capture diverse synchronized stereo target session #{number}",
                [
                    artifact(
                        f"{root}/session.json",
                        "bividi.calibration.stereo_session.v1",
                    )
                ],
                depends=("target_scale",),
                kind="measured_raw",
                notes=[
                    "Use #35 normalized/stable capture and preserve camera_a/camera_b identities.",
                    "Deliberately vary position, scale, tilt, roll, image-plane location, and edge coverage.",
                ],
            ),
            stage(
                f"{session_id}_inspect",
                f"Inspect target detection / coverage / image quality #{number}",
                [
                    artifact(
                        f"{root}/dataset-quality.json",
                        "bividi.calibration.stereo_dataset_quality.v1",
                    )
                ],
                depends=(f"{session_id}_capture",),
                kind="quality",
            ),
            stage(
                f"{session_id}_solve",
                f"Solve mono intrinsics + fixed-intrinsic stereo geometry #{number}",
                [
                    artifact(
                        f"{root}/stereo-calibration.json",
                        "bividi.calibration.stereo.v1",
                    )
                ],
                depends=(f"{session_id}_inspect",),
                kind="candidate",
                notes=["Do not use vendor nominal FOV/baseline as solver inputs."],
            ),
            stage(
                f"{session_id}_geometry",
                f"Compare recovered baseline with physical measurement #{number}",
                [
                    artifact(
                        f"{root}/geometry-review.json",
                        "bividi.calibration.stereo_geometry_review.v1",
                    )
                ],
                depends=(f"{session_id}_solve",),
                kind="quality",
            ),
            stage(
                f"{session_id}_rectify",
                f"Rectification inspection evidence #{number}",
                [artifact(f"{root}/rectified-sample.png")],
                depends=(f"{session_id}_solve",),
                kind="inspection",
            ),
            stage(
                f"{session_id}_kalibr_reference",
                f"Optional AprilGrid/Kalibr cross-check #{number}",
                [artifact(f"{root}/kalibr-reference.json", required=False)],
                depends=(f"{session_id}_solve",),
                runtime="external_kalibr",
                kind="optional_reference",
                notes=[
                    "Optional reference only; ROS/Kalibr is not a Bividi runtime dependency."
                ],
            ),
        ]
        repeatability_dependencies.append(f"{session_id}_geometry")

    stages += [
        stage(
            "repeatability",
            "Compare independent stereo solves",
            [
                artifact(
                    "final/repeatability.json",
                    "bividi.calibration.stereo_repeatability.v1",
                )
            ],
            depends=tuple(repeatability_dependencies),
            kind="quality",
        ),
        stage(
            "promotion",
            "Hash-bind target/session/quality/geometry/repeatability evidence",
            [
                artifact(
                    "final/stereo-evidence.json",
                    "bividi.calibration.stereo_evidence_manifest.v1",
                )
            ],
            depends=("repeatability",),
            kind="promotion",
            notes=[
                "Use promotion profile only after explicit target/dataset/solve/geometry/repeatability gates PASS under a named policy.",
                "PROMOTION_READY is a controlled evidence disposition, not independent proof of physical accuracy.",
            ],
        ),
    ]
    return stages


def manifest(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "campaign_id": args.campaign_id,
        "created_utc": utc(),
        "specimen": {"model": args.model, "serial": args.serial},
        "capture": {
            "device_index": args.device,
            "mode_index": args.mode,
            "pixel_format": args.pixel_format,
            "width": args.width,
            "height": args.height,
            "camera_mapping_evidence": args.camera_mapping_evidence,
        },
        "session_count": args.session_count,
        "policy_source": args.policy_source,
        "dependencies": {
            "host_acquisition_issue": 35,
            "stereo_calibration_issue": 8,
            "depth_issue": 9,
            "camera_imu_issue": 47,
            "vio_issue": 46,
        },
        "stages": build_stages(args.session_count),
        "guardrails": [
            "No numeric acceptance threshold is invented by this planner.",
            "camera_a/camera_b are not renamed left/right without #35 physical mapping evidence.",
            "Vendor nominal FOV/baseline are reference-only, not measured calibration.",
            "#9 metric-depth and #46 live-VIO accuracy claims remain blocked until measured calibration is frozen.",
        ],
        "provenance": {
            "tool": COMPATIBILITY_TOOL_NAME,
            "tool_version": TOOL_VERSION,
        },
    }


def runbook(campaign: dict[str, Any]) -> str:
    lines = [
        f"# Stereo Physical Calibration Campaign — {campaign['campaign_id']}",
        "",
        f"Specimen: `{campaign['specimen']['model']}` / `{campaign['specimen']['serial']}`  ",
        f"Device/mode: `{campaign['capture']['device_index']}` / `{campaign['capture']['mode_index']}`  ",
        f"Image: `{campaign['capture']['width']}x{campaign['capture']['height']} {campaign['capture']['pixel_format']}`",
        "",
        "## Execution rule",
        "",
        "Target scale first; diverse captures second; solve only after dataset inspection; promotion only after independent repeatability.",
        "",
    ]
    for index, item in enumerate(campaign["stages"], 1):
        dependencies = ", ".join(item["depends_on"]) if item["depends_on"] else "none"
        outputs = ", ".join(output["path"] for output in item["outputs"])
        lines += [
            f"### {index}. `{item['id']}` — {item['title']}",
            "",
            f"Runtime: `{item['runtime']}`  ",
            f"Evidence: `{item['evidence_class']}`  ",
            f"Depends on: `{dependencies}`  ",
            f"Expected output(s): `{outputs}`",
            "",
        ]
        for note in item["notes"]:
            lines.append(f"- {note}")
        if item["notes"]:
            lines.append("")

    lines += [
        "## Capture coverage procedure",
        "",
        "- Fill center and all image quadrants/edges; do not only collect centered frontal boards.",
        "- Vary board distance/apparent scale and out-of-plane tilt around both axes.",
        "- Include roll variation.",
        "- Keep motion blur and clipping visible to the dataset inspector rather than deleting weak frames silently.",
        "- Preserve rejected/weak-pair evidence in the quality report; re-capture instead of accepting poor coverage.",
        "",
        "## Final rule",
        "",
        "The selected artifact must be included in the repeatability campaign and be hash-bound by the final evidence manifest. Explicit thresholds must come from the recorded lab/product policy.",
        "",
    ]
    return "\n".join(lines)


def write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise CampaignError(f"{path}: expected {SCHEMA}")
    return data


def audit(path: Path) -> dict[str, Any]:
    campaign = load(path)
    root = path.parent
    states: dict[str, str] = {}
    details: list[dict[str, Any]] = []

    for item in campaign["stages"]:
        dependencies_complete = all(
            states.get(dependency) == "complete" for dependency in item["depends_on"]
        )
        outputs: list[dict[str, Any]] = []
        required_ok = True
        any_present = False
        for output in item["outputs"]:
            candidate = root / output["path"]
            present = candidate.is_file()
            any_present = any_present or present
            schema_ok: bool | None = None
            if present and output.get("schema"):
                try:
                    value = json.loads(candidate.read_text(encoding="utf-8"))
                    schema_ok = (
                        isinstance(value, dict) and value.get("schema") == output["schema"]
                    )
                except (OSError, json.JSONDecodeError):
                    schema_ok = False
            if output.get("required", True) and (not present or schema_ok is False):
                required_ok = False
            outputs.append(
                {
                    "path": output["path"],
                    "required": output.get("required", True),
                    "present": present,
                    "schema_ok": schema_ok,
                }
            )

        has_required = any(output.get("required", True) for output in item["outputs"])
        if required_ok and (has_required or any_present):
            state = "complete"
        elif dependencies_complete:
            state = "ready"
        else:
            state = "blocked"
        states[item["id"]] = state
        details.append({"id": item["id"], "state": state, "outputs": outputs})

    return {
        "schema": AUDIT_SCHEMA,
        "campaign_id": campaign["campaign_id"],
        "summary": {
            "stages": len(states),
            "complete": sum(value == "complete" for value in states.values()),
            "ready": sum(value == "ready" for value in states.values()),
            "blocked": sum(value == "blocked" for value in states.values()),
        },
        "stages": details,
        "promotion_artifact_present": states.get("promotion") == "complete",
        "note": "Presence/schema audit only; quality/hash/policy verification remains owned by the evidence tools.",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        args = argparse.Namespace(
            campaign_id="synthetic",
            model="S",
            serial="1",
            device=0,
            mode=0,
            pixel_format="GRAY8",
            width=1280,
            height=720,
            camera_mapping_evidence="synthetic",
            session_count=2,
            policy_source=None,
        )
        campaign = manifest(args)
        write(root / "campaign.json", campaign)
        (root / "RUNBOOK.md").write_text(runbook(campaign), encoding="utf-8")
        result = audit(root / "campaign.json")
        assert result["summary"]["complete"] == 0

        target = root / campaign["stages"][0]["outputs"][0]["path"]
        target.parent.mkdir(parents=True)
        target.write_text(
            json.dumps({"schema": "bividi.calibration.stereo_target.v1"}),
            encoding="utf-8",
        )
        result = audit(root / "campaign.json")
        assert result["stages"][0]["state"] == "complete"
        assert campaign["provenance"]["tool"] == COMPATIBILITY_TOOL_NAME

        try:
            build_stages(1)
            raise AssertionError("expected CampaignError")
        except CampaignError:
            pass
    print("Stereo physical campaign planner self-test: PASS")


def parse(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    subparsers = parser.add_subparsers(dest="cmd")

    initialize = subparsers.add_parser("init")
    initialize.add_argument("root", type=Path)
    initialize.add_argument("--campaign-id", required=True)
    initialize.add_argument("--model", required=True)
    initialize.add_argument("--serial", required=True)
    initialize.add_argument("--device", type=int, required=True)
    initialize.add_argument("--mode", type=int, required=True)
    initialize.add_argument("--pixel-format", required=True)
    initialize.add_argument("--width", type=int, required=True)
    initialize.add_argument("--height", type=int, required=True)
    initialize.add_argument("--camera-mapping-evidence")
    initialize.add_argument("--session-count", type=int, required=True)
    initialize.add_argument("--policy-source")

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("manifest", type=Path)
    audit_parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    if args.self_test:
        self_test()
        return 0

    if args.cmd == "init":
        root = args.root.resolve()
        if root.exists() and any(root.iterdir()):
            raise CampaignError(f"campaign root is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        campaign = manifest(args)
        write(root / "campaign.json", campaign)
        (root / "RUNBOOK.md").write_text(runbook(campaign), encoding="utf-8")
        print(root / "campaign.json")
        print(root / "RUNBOOK.md")
        return 0

    if args.cmd == "audit":
        result = audit(args.manifest.resolve())
        text = json.dumps(result, indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0

    raise CampaignError("choose init/audit or --self-test")


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """CLI wrapper preserving the historical error/exit-code contract."""

    try:
        return main(argv)
    except CampaignError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
