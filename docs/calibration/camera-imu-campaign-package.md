# Package-native camera↔IMU physical campaign planner

`bividi-calib camera-imu campaign` is the installed-package entry point for the camera↔IMU physical calibration campaign planner. It packages the historical `tools/plan_camera_imu_physical_campaign.py` workflow without changing its campaign schema, stage graph, audit semantics, or calibration-policy boundary.

## Boundary

The planner is orchestration, not a calibration solver or quality gate. It creates a deterministic campaign manifest and Markdown runbook, then audits whether expected artifacts are present and, where declared, carry the expected schema. It does not acquire a Nori device, execute Kalibr, estimate `T_cam_imu`, estimate time offset, calculate IMU noise, choose calibration values, or invent acceptance thresholds.

A package migration is therefore not evidence that the physical #47 campaign has been executed. Real camera/IMU acquisition, device timing, AprilGrid observations, external Kalibr execution, leaf quality evidence, repeatability, and final promotion still require their respective runtime/laboratory steps.

## Installed command

The normal package entry point is:

```text
bividi-calib camera-imu campaign --self-test
```

Create a campaign directory with:

```text
bividi-calib camera-imu campaign init <root> \
  --campaign-id <id> \
  --model <model> \
  --serial <serial> \
  --device <index> \
  --mode <index> \
  --camera-time-reference <exposure_start|exposure_midpoint|exposure_end> \
  --dynamic-session-count <N> \
  [--policy-source <name>]
```

`--dynamic-session-count` must be at least two because the campaign contains an independent-solve repeatability stage.

Audit a campaign with:

```text
bividi-calib camera-imu campaign audit <root>/campaign.json [--output audit.json]
```

The legacy `tools/plan_camera_imu_physical_campaign.py` path remains a thin compatibility wrapper around the installed implementation.

## Frozen campaign identity

The migration preserves:

- campaign schema `bividi.calibration.camera_imu_physical_campaign.v1`;
- audit schema `bividi.calibration.camera_imu_physical_campaign_audit.v1`;
- historical provenance `tool = plan_camera_imu_physical_campaign.py`, `tool_version = 1`;
- Kalibr backend `ethz-asl/kalibr` pinned to revision `1f60227442d25e36365ef5f72cd80b9666d73467`;
- time definition `t_imu_s = t_camera_reference_s + offset_s`;
- camera timestamp references `exposure_start`, `exposure_midpoint`, and `exposure_end`;
- issue dependencies #35 acquisition, #8 stereo calibration, #47 camera↔IMU calibration, and #46 downstream VIO.

The implementation file keeps the historical basename specifically because the versioned campaign manifest records `Path(__file__).name` as provenance.

## Stage graph

The campaign first builds the measured IMU evidence chain: short stationary capture, timestamp/cadence audit, stationary statistics, long Allan/noise capture and analysis, six-position accelerometer evidence, controlled gyro-rotation evidence, provenance binding, declared-vs-measured configuration consistency, and IMU promotion.

Each dynamic camera↔IMU session then contains capture, Kalibr-session preparation, excitation evidence, exact AprilGrid target observations, target coverage, external Kalibr solve, solver-quality evidence, imported calibration candidate, and device-time temporal review. Exact target-observation extraction and the actual solve remain `external_kalibr` runtime stages rather than Bividi Core functionality.

After all independent sessions, the graph ends with cross-session spatial/temporal repeatability and the final evidence-promotion artifact.

## Audit semantics

The audit deliberately checks **presence and declared JSON schema only**. For each stage:

- all expected outputs present and schema-valid means `complete`;
- otherwise, if dependencies are complete, the stage is `ready`;
- otherwise it is `blocked`.

This preserves an important historical behavior: if a stage's expected outputs already exist and match their declared schemas, the audit may mark that stage `complete` even when dependency stages are not complete. That behavior is intentional for this migration because the audit is not a provenance or quality verifier.

Likewise, `promotion_artifact_present: true` means only that the expected final promotion artifact is present with the expected schema according to this orchestration audit. It does **not** mean the promotion gate returned `PROMOTION_READY`, that hashes/cross-links were verified, or that the physical calibration is accurate. Use the package-native evidence tools and `camera-imu promote` for those checks.

## Policy ownership

The campaign records `policy_source` as orchestration metadata but never interprets or manufactures leaf numeric limits. Motion excitation, target coverage, solver residuals, temporal review, repeatability, and final promotion retain their own explicit evidence/policy semantics. Presence of a policy-source string in the campaign manifest is not itself a quality PASS.

The command contract therefore uses:

```text
output_role = orchestration-json-markdown
policy_role = recorded-orchestration-metadata
evaluated_fail_exit = none
```

## Exit vocabulary

The package adapter uses the frozen #60 process vocabulary. Successful self-test, `init`, and `audit` return `0`. Usage, input, domain, manifest read/schema, and write failures return `2`. This command never returns `3`, because a campaign presence/schema audit does not perform a completed quality-policy evaluation.

An incomplete or blocked campaign is still a successful audit operation and returns `0`; the stage states are the audit result.

## Validation

The package migration is covered by synthetic/package tests for source-independent routing, package and compatibility-wrapper self-tests, frozen schemas/provenance/time semantics, the minimum-two-session invariant, stage graph and external-runtime boundaries, deterministic initialization, incomplete-audit behavior, the presence/schema-only promotion boundary, `0/2` exit normalization, and command-contract metadata. These tests are suitable for ordinary CI; they do not substitute for real camera/IMU hardware qualification or external Kalibr execution.
