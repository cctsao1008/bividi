# Calibrated depth preview in `bividi-web`

Status: optional engineering visualization for Issue #9. It consumes the normalized `SensorObservation` boundary and the existing deterministic stereo-depth processor. It is not a new raw-data path and it does not promote synthetic/replay evidence into a physical AR0234 accuracy claim.

## Why the web preview uses normalized observations

`CaptureSession::latest_stereo_preview()` is intentionally a BGR engineering/UI surface. It may resize, convert, or otherwise prepare pixels for display and therefore is not the authoritative input for geometry.

The calibrated preview instead follows:

```text
ReplaySource
    ↓
SensorObservation + SensorCapabilities
    ↓
ObservationSnapshotSource
    ↓
StereoDepthObservationProcessor
    ↓
StereoSGBM float disparity + validity mask
    ↓
metric depth [m]
    ↓
8-bit UI-only disparity/depth previews
```

This keeps the same synchronization, calibration-identity, continuity, sequence, and missing-camera gates already used by the #9/#59 integration tests.

## Enabling it

Depth is disabled by default. An explicit promoted/test calibration artifact must be supplied:

```bash
bividi-web \
  --source replay \
  --session <recording-session> \
  --depth-calibration <stereo-calibration.json> \
  --depth-pair stereo0
```

Current source support is intentionally narrow: the source must expose normalized observations through `ObservationSnapshotSource`. `ReplayCaptureSession` does this today. Supplying `--depth-calibration` to a source that only exposes the legacy preview surface is rejected at startup rather than silently deriving geometry from UI pixels.

The selected calibration artifact is loaded through `bividi::depth::load_calibration_json()` and therefore remains subject to the #8/#9 schema and geometry checks.

## HTTP surface

When enabled:

```text
GET /api/depth/status
GET /disparity.jpg
GET /depth.jpg
```

`/api/depth/status` reports the selected calibration/pair, source sequence, synchronization state, continuity/reset generation, validity fraction, and explicit processed/rejected disposition.

The image endpoints are visualization products only. The numerical `CV_32F` disparity/depth matrices and validity mask remain inside the depth result contract; JPEG normalization is never used as a numeric geometry representation.

## Snapshot caching

The browser polls status and fetches disparity/depth images independently. `StereoDepthObservationProcessor` owns chronology state, so processing the same source observation twice would incorrectly look like a duplicate sequence.

`StereoDepthSnapshotProcessor` therefore caches one normalized source snapshot and one derived result. Multiple HTTP requests for that same snapshot reuse the cached result. A newly published frame gets a new derived revision. The cache retains the original `FrameLease`, so replay reset/re-materialization cannot masquerade as the same backing image instance.

## Rejection behavior

No plausible depth image is retained or fabricated after a rejected current observation. The derived panel reports the consumer disposition and the image endpoint renders an explicit unavailable/rejected placeholder.

Examples:

```text
missing camera          -> rejected_camera_missing
unsynchronized pair     -> rejected_synchronization
calibration mismatch    -> rejected_calibration_identity
duplicate/backward seq  -> rejected_sequence_non_monotonic
continuity boundary     -> reset derived chronology before processing
```

`unknown` synchronization may remain acceptable for synthetic/replay policy, but it stays `unknown` in the web status. The UI never upgrades it to `synchronized`.

## Evidence boundary

A working web disparity/depth panel proves software plumbing and algorithmic behavior only.

Physical AR0234 metric-depth claims still require, at minimum:

```text
#35 measured live acquisition / camera mapping / synchronization evidence
+
#8 promoted measured stereo calibration
+
range/error/invalid-rate/latency characterization
```

The browser console is an inspection surface, not an acceptance certificate.
