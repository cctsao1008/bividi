# Bividi Documentation Map

The current concrete reference-device line is **stereo AR0234 + IMU**. Core architecture remains platform/device independent.

## Architecture

- [`architecture.md`](architecture.md) — durable system boundary and dependency direction
- [`observation-interface.md`](observation-interface.md) — native `SensorCapabilities` / `SensorObservation` contract, timing domains, ownership, continuity, and compatibility rules
- [`host.md`](host.md) — hardware-independent host API and backend/adapter boundary
- [`native-runtime.md`](native-runtime.md) — C++/OpenCV production runtime and Python reference/oracle role
- [`viewer.md`](viewer.md) — minimal OpenCV diagnostic viewer and local control surface
- [`web-ui.md`](web-ui.md) — lightweight browser engineering console, HTTP/MJPEG boundary, and security posture
- [`recording.md`](recording.md) — native `SensorObservation` replay, viewer/web replay adapters, MCAP direction, and container-independence rule
- [`mcap-observation.md`](mcap-observation.md) — versioned Bividi-native `SensorObservation` MCAP profile, timestamp separation, camera payload integrity, and semantic round-trip contract
- [`replay-fault-injection.md`](replay-fault-injection.md) — deterministic versioned replay fault recipes, expected-disposition separation, and #35 physical-test boundary
- [`synthetic-sensorrig.md`](synthetic-sensorrig.md) — deterministic synthetic stereo-inertial rig, ground truth, replay-compatible fixtures, and synthetic-vs-physical evidence boundary

## Active reference device

- [`devices/decxin-ar0234.md`](devices/decxin-ar0234.md) — DECXIN AR0234 stereo + IMU module facts, purchased 100° configuration, interfaces, and current unknowns
- [`devices/decxin-nori-sdk-surface.md`](devices/decxin-nori-sdk-surface.md) — Nori_Xvision Windows/Linux SDK surface and backend constraints
- [`protocols/decxin-nori-timestamp-imu.md`](protocols/decxin-nori-timestamp-imu.md) — DECXIN/Nori timestamp and ICM42688 IMU transport format

## Characterization

- [`characterization/usb-uvc-test-plan.md`](characterization/usb-uvc-test-plan.md) — live host/interface characterization for the AR0234 reference device
- [`characterization/stereo-transport-test-plan.md`](characterization/stereo-transport-test-plan.md) — live camera A/B mapping and transport verification
- [`characterization/nori-live-characterization.md`](characterization/nori-live-characterization.md) — `bividi-nori-characterize` usage, artifacts, metrics, RSS/recovery trials, and clock-domain rules
- [`characterization/ar0234-qualification-protocol.md`](characterization/ar0234-qualification-protocol.md) — staged physical qualification from 60 s baseline through soak, software recovery, true USB fault testing, and regression comparison
- [`characterization/qualification-campaign-comparison.md`](characterization/qualification-campaign-comparison.md) — campaign manifests, stage-by-stage regression comparison, provenance deltas, and optional explicit gates

## Calibration

- [`calibration/calibration-cli.md`](calibration/calibration-cli.md) — consolidated `bividi-calib` stereo/IMU/camera↔IMU command surface and legacy-tool migration map
- [`calibration/stereo-calibration-readiness.md`](calibration/stereo-calibration-readiness.md) — #8 ChArUco/AprilGrid target contracts, paired-session curation, corner/image-plane quality, native OpenCV mono/stereo solve, rectification metrics, physical baseline review, repeatability, and final evidence promotion
- [`calibration/inertial-camera-imu.md`](calibration/inertial-camera-imu.md) — #47 IMU and camera↔IMU artifact semantics, SI units, frame/time-offset conventions, validation, and Kalibr adapter mapping
- [`calibration/camera-imu-timestamp-audit.md`](calibration/camera-imu-timestamp-audit.md) — lossless Nori IMU timestamp/raw-count recording plus device-domain exposure↔IMU cadence, rollover, and nearest-sample audit
- [`calibration/imu-stationary-analysis.md`](calibration/imu-stationary-analysis.md) — stationary raw-count bias/variance evidence with optional explicitly-provenanced SI scale conversion
- [`calibration/imu-allan-noise-lab.md`](calibration/imu-allan-noise-lab.md) — streaming Allan deviation, explicit fit windows, verified raw→SI scaling, and Kalibr noise-model candidate extraction
- [`calibration/imu-six-position-axis-lab.md`](calibration/imu-six-position-axis-lab.md) — six-pose gravity experiment for accelerometer axis/sign mapping, counts-per-g scale sanity, affine coupling evidence, and handedness parity
- [`calibration/imu-gyro-rotation-lab.md`](calibration/imu-gyro-rotation-lab.md) — controlled +/-XYZ turns for gyro bias-corrected integration, axis/sign mapping, pair symmetry, optional rate-scale evidence, and accel↔gyro frame comparison
- [`calibration/imu-calibration-provenance-gate.md`](calibration/imu-calibration-provenance-gate.md) — hash-bound session manifest tying specimen, SDK/firmware, camera mode, IMU range/ODR/filter declarations, raw traces, and analysis reports before calibration promotion
- [`calibration/imu-config-consistency-lab.md`](calibration/imu-config-consistency-lab.md) — measured-vs-declared accel range, gyro range, and device-timestamp ODR consistency checks without pretending to read sensor registers
- [`calibration/kalibr-dynamic-session.md`](calibration/kalibr-dynamic-session.md) — synchronized stereo+raw-IMU recorder, explicit ES/midpoint/EE timestamp mapping, hash-bound raw→SI conversion, Kalibr bundle staging, and legacy ROS1 upstream-solver adapter
- [`calibration/ros2-mcap-calibration-transport.md`](calibration/ros2-mcap-calibration-transport.md) — modern ROS2/rosbag2 MCAP transport adapter while keeping ROS1 isolated to upstream Kalibr compatibility
- [`calibration/camera-imu-dynamic-excitation.md`](calibration/camera-imu-dynamic-excitation.md) — common-time coverage, per-axis inertial activity, integrated rotation, and directionality proxies without claiming formal observability
- [`calibration/kalibr-target-coverage-lab.md`](calibration/kalibr-target-coverage-lab.md) — exact pinned-Kalibr AprilGrid observation export plus target-ID, image-plane, scale-proxy, and stereo joint-detection coverage evidence
- [`calibration/kalibr-result-import-review.md`](calibration/kalibr-result-import-review.md) — strict `T_cam_imu` / `timeshift_cam_imu` import, solver/session provenance, and device-time temporal evidence review without turning nearest-sample geometry into a fake offset estimator
- [`calibration/kalibr-solver-quality-gate.md`](calibration/kalibr-solver-quality-gate.md) — pinned Kalibr residual parser, normalized/physical fit evidence, stereo completeness checks, and optional requirement-based solver-quality gates
- [`calibration/camera-imu-repeatability.md`](calibration/camera-imu-repeatability.md) — repeated-solve SE(3)/time-offset consistency, compatibility gating, and optional requirement-based repeatability thresholds
- [`calibration/camera-imu-evidence-promotion-gate.md`](calibration/camera-imu-evidence-promotion-gate.md) — final hash-bound evidence graph with integrity/review/promotion profiles and explicit policy-controlled release to #46
- [`calibration/camera-imu-physical-campaign.md`](calibration/camera-imu-physical-campaign.md) — specimen-specific physical campaign planner/runbook that orders IMU, dynamic-session, Kalibr, repeatability, and promotion evidence without inventing acceptance thresholds

## Research / interoperability

- [`research/host-ai-interface-standards.md`](research/host-ai-interface-standards.md) — host/robotics/recording/AI standards audit
- [`research/bividi-llmc-lsmm-integration.md`](research/bividi-llmc-lsmm-integration.md) — Bividi → llm.c → lsmm.c boundary and provenance model
- [`research/transport-note.md`](research/transport-note.md) — short transport-independence note

## AI

- [`ai-mcp.md`](ai-mcp.md) — MCP adapter role and run notes

Historical camera-candidate research is intentionally kept in Git history / Issues rather than the current documentation tree.
