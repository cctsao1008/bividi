# Stereo depth preview in `bividi-web`

Status: optional engineering visualization for Issue #9. Two intentionally different modes exist:

- `--quick-depth`: live **uncalibrated** disparity / relative near-far preview for fast physical bring-up;
- `--depth-calibration <artifact>`: calibrated derived geometry through the normal #8/#9 observation path.

The modes are mutually exclusive. The quick mode must never be presented as metric depth.

## Quick live preview

For the delivered DECXIN AR0234 rig, physical occlusion testing under #35 established:

```text
observer facing the lenses:
front-view left  -> camera_a
front-view right -> camera_b

rig-forward stereo convention:
left  = camera_b
right = camera_a
```

Quick depth consumes `CaptureSession::latest_stereo_preview()` only as an engineering visualization surface:

```text
NoriCaptureSession (60 fps acquisition remains independent)
        ↓
latest paired BGR preview
        ↓
resize to 640x400
        ↓
raw StereoSGBM disparity
        ↓
image-derived auto-rectification search
  GFTT corners + NCC patch matches
        ↓
RANSAC fundamental matrix
        ↓
stereoRectifyUncalibrated() homographies
        ↓
freeze accepted homographies
        ↓
warp + StereoSGBM worker, target ~10 fps
        ↓
uncalibrated disparity + relative near/far heatmap
        ↓
web panel
```

The auto-rectification transform is estimated from live image correspondences only. It is accepted only when RANSAC support is adequate, the resulting homographies pass basic geometric sanity checks, and the median vertical correspondence residual is sufficiently small. Once accepted, the homographies are frozen until reconnect/reset rather than being re-estimated every frame.

Enable it with:

```powershell
.\build-nori-opencv\Release\bividi-web.exe `
  --source nori `
  --device 0 `
  --mode 0 `
  --timeout-ms 2000 `
  --quick-depth
```

Then open:

```text
http://127.0.0.1:8080
```

Quick mode still does **not** apply measured camera intrinsics, a distortion model, measured stereo extrinsics/baseline, or a `Q` matrix. `stereoRectifyUncalibrated()` only supplies projective image homographies from the current live correspondences. The result remains useful for visual confirmation that the live stereo pair contains coherent disparity structure and that near/far motion behaves plausibly, but it cannot support claims such as `0.63 m` or any other metric distance.

The quick worker runs downstream from capture and samples the latest available paired preview. It does not back-pressure the 60 fps Nori acquisition path merely to keep the browser depth panel current.

### Quick-depth evidence surfaced in the UI

`/api/depth/status` includes both the raw and current disparity validity plus the auto-rectification diagnostics:

```text
raw_valid_fraction
valid_fraction
rectified
rectification_attempts
rectification_matches
rectification_inliers
median_vertical_before_px
median_vertical_after_px
rectification_reason
processing_ms
```

If no acceptable transform has been found, the service continues to display the raw unrectified disparity rather than manufacturing a corrected result. If an accepted transform later produces a clearly destructive valid-disparity collapse, the current frame falls back to raw disparity and reports the fallback explicitly.

## Calibrated preview

The calibrated path does not derive geometry from UI pixels. It follows the normalized observation boundary:

```text
ObservationSnapshotSource
    ↓
SensorObservation + SensorCapabilities
    ↓
StereoDepthObservationProcessor
    ↓
calibration-bound rectification
    ↓
StereoSGBM float disparity + validity mask
    ↓
metric depth [m]
    ↓
8-bit UI-only disparity/depth previews
```

Enable it with a promoted/test calibration artifact:

```bash
bividi-web \
  --source replay \
  --session <recording-session> \
  --depth-calibration <stereo-calibration.json> \
  --depth-pair stereo0
```

Live Nori sessions now also expose `ObservationSnapshotSource`; a measured live calibrated run remains subject to the #8 calibration/evidence gate.

The selected calibration artifact is loaded through `bividi::depth::load_calibration_json()` and remains subject to the #8/#9 schema and geometry checks.

## HTTP surface

When either mode is enabled:

```text
GET /api/depth/status
GET /disparity.jpg
GET /depth.jpg
```

For quick mode, `/disparity.jpg` is the auto-rectified disparity when an accepted transform is active, otherwise the raw unrectified fallback. `/depth.jpg` is always a **relative near/far heatmap**, not metric depth. `/api/depth/status` reports `mode=quick_uncalibrated`, `metric=false`, the rectification state/evidence, source sequence, disparity validity, processing time, and explicit camera ordering.

For calibrated mode, `/api/depth/status` reports the selected calibration/pair, source sequence, synchronization state, continuity/reset generation, validity fraction, and processed/rejected disposition.

The image endpoints are visualization products only. Calibrated numerical `CV_32F` disparity/depth matrices and validity masks remain inside the depth result contract; JPEG normalization is never used as a numeric geometry representation.

## Snapshot caching

The calibrated browser path uses `StereoDepthSnapshotProcessor` so independent status/disparity/depth HTTP requests reuse one normalized observation result instead of manufacturing duplicate-sequence chronology faults.

Quick mode has its own bounded-rate background worker and cached image result. HTTP requests only read the latest cache; they do not run StereoSGBM or rectification estimation inside the request path.

## Rejection / unavailable behavior

No plausible calibrated depth image is retained or fabricated after a rejected current observation. The panel reports the consumer disposition and the image endpoint renders an explicit unavailable/rejected placeholder.

Quick mode reports a waiting placeholder until a paired BGR preview exists. Rectification-search failures remain visible while raw disparity continues. Processing errors are reported explicitly rather than silently substituting a previous result.

## Evidence boundary

A working quick disparity panel proves that the live stereo pair contains matchable image structure and can support an image-derived projective epipolar alignment under the current scene when auto-rectification locks. It does not prove camera calibration quality, measured stereo synchronization, or metric accuracy.

Physical AR0234 metric-depth claims still require, at minimum:

```text
#35 measured live acquisition / camera mapping / synchronization evidence
+
#8 promoted measured stereo calibration
+
range/error/invalid-rate/latency characterization
```

The browser console is an inspection surface, not an acceptance certificate.
