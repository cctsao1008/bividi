# Stereo calibration live capture (#8)

The physical #8 campaign must reuse the stable normalized acquisition path from #35 rather than opening Nori/V4L2 directly inside calibration logic.

Bividi already has the appropriate live recorder:

```text
bividi-nori-calib-record
```

It creates a new session directory with paired lossless monochrome images under:

```text
<output>/camera_a/
<output>/camera_b/
```

and also writes `capture.json`, `frames.csv`, and `imu.csv`. `frames.csv` preserves frame sequence, host receive time, SDK timestamp representation, exposure start/end raw timestamps, exposure start/end extended timestamps, and the exact camera A/B image paths. The extra IMU trace is useful to #47 and does not change the #8 stereo-geometry contract. Camera names remain `camera_a` / `camera_b` until #35 physically verifies which optical side each stream represents.

## Recommended capture flow

First probe the real device/mode and finish #35 camera mapping. Then record one independent calibration session at a time, for example:

```bash
bividi-nori-calib-record \
  --device 0 \
  --mode 0 \
  --duration-s 120 \
  --warmup-frames 30 \
  --frame-stride 1 \
  --png-compression 1 \
  --output-dir ar0234-stereo-session-01
```

The exact duration and retained-frame count are experiment choices, not universal acceptance constants. The target should be deliberately moved through center, edges, corners, multiple distances/scales, positive/negative tilt about both axes, and roll. Avoid turning frame count into the objective; geometric diversity and usable detections are what matter.

## Import the recorder evidence directly

For a physical AR0234 campaign, do **not** rebuild the session from image filenames and then re-type device/mode fields that the recorder already knew. Import the recorder output directly:

```bash
python tools/stereo_calibration_workbench.py session-recorder \
  --session-id ar0234-stereo-01 \
  --target target/target.json \
  --recorder-dir ar0234-stereo-session-01 \
  --model DECXIN-AR0234 \
  --camera-mapping-evidence "#35 physical A/B mapping record" \
  --output ar0234-stereo-session-01/session.json
```

`session-recorder` reads the recorder's `capture.json` and `frames.csv`, derives the saved per-camera PNG geometry, carries the real device serial/mode/transport provenance forward, and retains per-pair:

```text
source frame index
frame sequence
host_receive_monotonic_ns
SDK timestamp representation
ES / EE raw timestamps
ES / EE extended timestamps
camera_a / camera_b image paths
camera_a / camera_b SHA-256
```

The session also hash-binds `capture.json` and `frames.csv`. The #8 promotion gate re-verifies these nested acquisition artifacts and the image hashes, so changing a PNG or recorder trace after analysis invalidates promotion evidence.

The generic `session` command remains useful for synthetic/imported/offline datasets that did not originate from the Nori recorder. For the current measured AR0234 physical campaign, `session-recorder` is the required provenance-preserving path.

## Solver invariant rule

`inspect` is a curation tool, not a correctness prerequisite for `solve`. The solver independently rejects undecodable images, image geometry that differs from the session contract, malformed detector IDs, changed hash-bound images, and changed recorder source traces before calibration math runs.

## Retention rule

Keep the raw paired PNG session outside normal Git history. Retain the session manifest, quality report, calibration artifact, rectification evidence, physical baseline review, and final hashes with the experiment evidence bundle.

Do not rename `camera_a` / `camera_b` to left/right merely because the preview appears visually obvious. The mapping must come from the explicit #35 physical observation.
