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
    "interop-yaml-and-machine-manifest",
    "interop-transport-artifact",
    "interop-transport-and-machine-manifest",
    "staging-bundle-and-machine-manifest",
    "observation-csv-and-machine-manifest",
    "calibration-artifact-and-import-manifest",
    "evidence-manifest-and-verification-report",
    "validation-result",
    "inspection-image",
]
PolicyRole = Literal[
    "named-source-required-for-explicit-gates",
    "promotion-requires-manifest-and-evidence-policy",
    "presentation-only",
    "recorded-orchestration-metadata",
    "analysis-parameter-no-acceptance-gate",
    "explicit-scale-source-no-acceptance-gate",
    "explicit-analysis-parameters-no-acceptance-gate",
    "candidate-analysis-no-acceptance-gate",
    "explicit-operator-gates-no-default-thresholds",
    "explicit-operator-gates-with-structural-fail-no-default-thresholds",
    "structural-provenance-gate-no-numerical-policy",
    "structural-validation-no-acceptance-gate",
    "measured-fields-required-synthetic-opt-in",
    "measured-evidence-required-synthetic-opt-in",
    "reviewed-external-runtime-no-acceptance-gate",
    "external-runtime-transport-no-acceptance-gate",
    "candidate-import-no-acceptance-gate",
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


STEREO_WORKBENCH_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="stereo",
        name="target",
        module="bividi.calibration.stereo_workbench_command",
        compatibility_tool="stereo_calibration_workbench.py",
        output_role="machine-evidence-json",
        policy_role="recorded-orchestration-metadata",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="session",
        module="bividi.calibration.stereo_workbench_command",
        compatibility_tool="stereo_calibration_workbench.py",
        output_role="machine-evidence-json",
        policy_role="recorded-orchestration-metadata",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="session-recorder",
        module="bividi.calibration.stereo_workbench_command",
        compatibility_tool="stereo_calibration_workbench.py",
        output_role="machine-evidence-json",
        policy_role="recorded-orchestration-metadata",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="inspect",
        module="bividi.calibration.stereo_workbench_command",
        compatibility_tool="stereo_calibration_workbench.py",
        output_role="machine-evidence-json",
        policy_role="explicit-operator-gates-no-default-thresholds",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="solve",
        module="bividi.calibration.stereo_workbench_command",
        compatibility_tool="stereo_calibration_workbench.py",
        output_role="machine-evidence-json",
        policy_role="explicit-operator-gates-no-default-thresholds",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="validate",
        module="bividi.calibration.stereo_workbench_command",
        compatibility_tool="stereo_calibration_workbench.py",
        output_role="validation-result",
        policy_role="structural-validation-no-acceptance-gate",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="stereo",
        name="rectify",
        module="bividi.calibration.stereo_workbench_command",
        compatibility_tool="stereo_calibration_workbench.py",
        output_role="inspection-image",
        policy_role="presentation-only",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
)


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


IMU_NOISE_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="imu",
        name="allan",
        module="bividi.calibration.imu_allan_command",
        compatibility_tool="analyze_imu_allan.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-analysis-parameters-no-acceptance-gate",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
)


IMU_AXIS_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="imu",
        name="six-position",
        module="bividi.calibration.imu_six_position_command",
        compatibility_tool="analyze_imu_six_position.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="candidate-analysis-no-acceptance-gate",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="imu",
        name="gyro-rotation",
        module="bividi.calibration.imu_gyro_rotation_command",
        compatibility_tool="analyze_imu_gyro_rotation.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="candidate-analysis-no-acceptance-gate",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
)


IMU_CONFIG_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="imu",
        name="config-consistency",
        module="bividi.calibration.imu_config_consistency_command",
        compatibility_tool="analyze_imu_config_consistency.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-operator-gates-no-default-thresholds",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


IMU_PROVENANCE_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="imu",
        name="provenance",
        module="bividi.calibration.imu_provenance_command",
        compatibility_tool="imu_calibration_provenance.py",
        output_role="machine-evidence-json",
        policy_role="structural-provenance-gate-no-numerical-policy",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


IMU_INTEROP_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="imu",
        name="export-kalibr",
        module="bividi.calibration.kalibr_imu_export_command",
        compatibility_tool="export_kalibr_imu.py",
        output_role="interop-yaml-and-machine-manifest",
        policy_role="measured-fields-required-synthetic-opt-in",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
)


CAMERA_IMU_TRANSPORT_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="ros1-bag",
        module="bividi.calibration.kalibr_rosbag_command",
        compatibility_tool="write_kalibr_rosbag.py",
        output_role="interop-transport-artifact",
        policy_role="external-runtime-transport-no-acceptance-gate",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="camera-imu",
        name="ros2-mcap",
        module="bividi.calibration.ros2_mcap_command",
        compatibility_tool="write_ros2_calibration_mcap.py",
        output_role="interop-transport-and-machine-manifest",
        policy_role="external-runtime-transport-no-acceptance-gate",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
)


CAMERA_IMU_STAGING_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="prepare",
        module="bividi.calibration.kalibr_dynamic_session_command",
        compatibility_tool="prepare_kalibr_dynamic_session.py",
        output_role="staging-bundle-and-machine-manifest",
        policy_role="measured-evidence-required-synthetic-opt-in",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
)


CAMERA_IMU_EVIDENCE_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="excitation",
        module="bividi.calibration.camera_imu_excitation_command",
        compatibility_tool="analyze_camera_imu_excitation.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-operator-gates-with-structural-fail-no-default-thresholds",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


CAMERA_IMU_TARGET_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="target-observations",
        module="bividi.calibration.kalibr_target_observations_command",
        compatibility_tool="export_kalibr_target_observations.py",
        output_role="observation-csv-and-machine-manifest",
        policy_role="reviewed-external-runtime-no-acceptance-gate",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
    CalibrationCommandContract(
        group="camera-imu",
        name="target-coverage",
        module="bividi.calibration.kalibr_target_coverage_command",
        compatibility_tool="analyze_kalibr_target_coverage.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-operator-gates-no-default-thresholds",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


CAMERA_IMU_IMPORT_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="import-kalibr",
        module="bividi.calibration.kalibr_camera_imu_import_command",
        compatibility_tool="import_kalibr_camera_imu.py",
        output_role="calibration-artifact-and-import-manifest",
        policy_role="candidate-import-no-acceptance-gate",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
)


CAMERA_IMU_SOLVER_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="solver-quality",
        module="bividi.calibration.kalibr_solver_quality_command",
        compatibility_tool="analyze_kalibr_solver_quality.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-operator-gates-with-structural-fail-no-default-thresholds",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


CAMERA_IMU_TEMPORAL_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="temporal-review",
        module="bividi.calibration.camera_imu_temporal_review_command",
        compatibility_tool="review_camera_imu_time_offset.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-operator-gates-no-default-thresholds",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


CAMERA_IMU_REPEATABILITY_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="repeatability",
        module="bividi.calibration.camera_imu_repeatability_command",
        compatibility_tool="compare_camera_imu_calibrations.py",
        output_role="machine-evidence-json-and-human-markdown",
        policy_role="explicit-operator-gates-no-default-thresholds",
        emits_versioned_provenance=False,
        tool_version=None,
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


CAMERA_IMU_PROMOTION_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="promote",
        module="bividi.calibration.camera_imu_provenance_command",
        compatibility_tool="camera_imu_calibration_provenance.py",
        output_role="evidence-manifest-and-verification-report",
        policy_role="promotion-requires-manifest-and-evidence-policy",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=EXIT_EVALUATED_FAIL,
    ),
)


CAMERA_IMU_CAMPAIGN_COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    CalibrationCommandContract(
        group="camera-imu",
        name="campaign",
        module="bividi.calibration.camera_imu_campaign_command",
        compatibility_tool="plan_camera_imu_physical_campaign.py",
        output_role="orchestration-json-markdown",
        policy_role="recorded-orchestration-metadata",
        emits_versioned_provenance=True,
        tool_version="1",
        evaluated_fail_exit=None,
    ),
)


COMMAND_CONTRACTS: tuple[CalibrationCommandContract, ...] = (
    STEREO_WORKBENCH_COMMAND_CONTRACTS
    + STEREO_COMMAND_CONTRACTS
    + IMU_COMMAND_CONTRACTS
    + IMU_NOISE_COMMAND_CONTRACTS
    + IMU_AXIS_COMMAND_CONTRACTS
    + IMU_CONFIG_COMMAND_CONTRACTS
    + IMU_PROVENANCE_COMMAND_CONTRACTS
    + IMU_INTEROP_COMMAND_CONTRACTS
    + CAMERA_IMU_TRANSPORT_COMMAND_CONTRACTS
    + CAMERA_IMU_STAGING_COMMAND_CONTRACTS
    + CAMERA_IMU_EVIDENCE_COMMAND_CONTRACTS
    + CAMERA_IMU_TARGET_COMMAND_CONTRACTS
    + CAMERA_IMU_IMPORT_COMMAND_CONTRACTS
    + CAMERA_IMU_SOLVER_COMMAND_CONTRACTS
    + CAMERA_IMU_TEMPORAL_COMMAND_CONTRACTS
    + CAMERA_IMU_REPEATABILITY_COMMAND_CONTRACTS
    + CAMERA_IMU_PROMOTION_COMMAND_CONTRACTS
    + CAMERA_IMU_CAMPAIGN_COMMAND_CONTRACTS
)

_INDEX = {item.key: item for item in COMMAND_CONTRACTS}


def contract_for(group: str, name: str) -> CalibrationCommandContract:
    try:
        return _INDEX[(group, name)]
    except KeyError as exc:
        raise KeyError(f"no frozen calibration command contract for {group} {name}") from exc
