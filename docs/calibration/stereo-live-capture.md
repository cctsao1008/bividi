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

and also retains frame/IMU timing evidence for the same run. The extra IMU trace is useful to #47 and does not change the #8 stereo-geometry contract. Camera names remain `camera_a` / `camera_b` until #35 physically verifies which optical side each stream represents.

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

After capture, create the #8 session manifest over the generated image directories:

```bash
python tools/stereo_calibration_workbench.py session \
  --session-id ar0234-stereo-01 \
  --target target/target.json \
  --camera-a-dir ar0234-stereo-session-01/camera_a \
  --camera-b-dir ar0234-stereo-session-01/camera_b \
  --model DECXIN-AR0234 \
  --serial <physical-serial> \
  --device 0 --mode 0 \
  --pixel-format <actual-normalized/session-format> \
  --width <single-camera-width> \
  --height <single-camera-height> \
  --camera-mapping-evidence "#35 physical A/B mapping record" \
  --provenance measured \
  --output ar0234-stereo-session-01/session.json
```

## Retention rule

Keep the raw paired PNG session outside normal Git history. Retain the session manifest, quality report, calibration artifact, rectification evidence, physical baseline review, and final hashes with the experiment evidence bundle.

Do not rename `camera_a` / `camera_b` to left/right merely because the preview appears visually obvious. The mapping must come from the explicit #35 physical observation.
