"""Stable behavior contract for package-native calibration commands.

This module freezes behavior demonstrated by migrated calibration leaves. It is
descriptive/contractual metadata, not a replacement implementation layer:
artifact schemas, numerical gates, and evidence semantics remain owned by each
leaf module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EXIT_OK = 0
EXIT_USAGE_OR_DOMAIN_ERROR = 2
EXIT_EVALUATED_FAIL = 3

OutputRole = Literal[
    "machine-evidence-json",
    "human-report-markdown",
    "orchestration-json-markdown",
    "machine-evidence-json-and-human-markdown",
]
PolicyRole = Literal[
    "named-source-required-for-explicit-gates",
    "promotion-requires-manifest-and-evidence-policy",
    "presentation-only",
    "recorded-orchestration-metadata",
    "analysis-parameter-no-acceptance-gate",
    "explicit-scale-source-no-acceptance-gate",
]


@dataclass(frozen=True)
class CalibrationCommandContract:
    group: str
    name: str
    module: str
    compatibility_tool: str
    output_role: OutputRole
    policy_role: PolicyRole
    emits_versioned_provenance: bool
    tool_version: str | None
    evaluated_fail_exit: int | None

    @property
    def key(self) -> tuple[str, str]:
        return (self.group, self.name)


STEREO_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="stereo",
        name="target-scale",
        module="bividi.calibration.target_scale",
        compatibility_tool="review_calibration_target_scale.py",
        output_role="machine-evidence-json",
        policy_role="named-source-required-for-explicit-gates",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="geometry-review",
        module="bividi.calibration.stereo_geometry",
        compatibility_tool="review_stereo_geometry.py",
        output_role="machine-evidence-json",
        policy_role="named-source-required-for-explicit-gates",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="repeatability",
        module="bividi.calibration.stereo_repeatability",
        compatibility_tool="compare_stereo_calibrations.py",
        output_role="machine-evidence-json",
        policy_role="named-source-required-for-explicit-gates",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="promote",
        module="bividi.calibration.stereo_provenance",
        compatibility_tool="stereo_calibration_provenance.py",
        output_role="machine-evidence-json",
        policy_role="promotion-requires-manifest-and-evidence-policy",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="report",
        module="bividi.calibration.stereo_report",
        compatibility_tool="render_stereo_calibration_report.py",
        output_role="human-report-markdown",
        policy_role="presentation-only",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="campaign",
        module="bividi.calibration.stereo_campaign",
        compatibility_tool="plan_stereo_calibration_campaign.py",
        output_role="orchestration-json-markdown",
        policy_role="recorded-orchestration-metadata",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
)


IMU_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="imu",
        name="timing-audit",
        module="bividi.calibration.imu_timing",
        compatibility_tool="audit_imu_timing.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="analysis-parameter-no-acceptance-gate",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="imu",
        name="stationary",
        module="bividi.calibration.imu_stationary",
        compatibility_tool="analyze_imu_stationary.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-scale-source-no-acceptance-gate",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
)


COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    STEREO_COMMAND_CONTRACTS + IMU_COMMAND_CONTRACTS
)

_INDEX = {item.key: item for item in COMMAND_CONTRACTS}


def contract_for(group: str, name: str) -> CalibrationCommandContract:
    try:
        return _INDEX[(group, name)]
    except KeyError as exc:
        raise KeyError(f"no frozen calibration command contract for {group} {name}") from exc
