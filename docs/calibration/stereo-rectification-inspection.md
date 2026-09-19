# Stereo rectification inspection evidence

Issue #129 extends the existing package-native `bividi-calib stereo rectify` command without changing its default output.

The historical command remains:

```text
bividi-calib stereo rectify \
  --calibration calibration.json \
  --camera-a camera_a.png \
  --camera-b camera_b.png \
  --output rectified.png
```

That path still renders only the rectified `camera_a | camera_b` pair with horizontal epipolar guide lines.

## Evidence-grade inspection mode

Optional arguments activate the inspection path:

```text
bividi-calib stereo rectify \
  --calibration calibration.json \
  --camera-a camera_a.png \
  --camera-b camera_b.png \
  --output inspection.png \
  --include-originals \
  --target target.json \
  --evidence-output inspection.json
```

The diagnostic image then contains the original stereo pair above the rectified pair. When an explicit ChArUco target is supplied, detected corners are marked and common correspondences are projected through the calibration artifact's `K/D/R/P` rectification products. The rectified pair also carries correspondence lines so vertical disagreement is visible rather than judged only from guide lines.

## Machine evidence

`--evidence-output` writes:

```text
bividi.calibration.stereo_rectification_inspection.v1
```

The artifact SHA-256 binds:

- the stereo calibration artifact;
- camera A input image;
- camera B input image;
- explicit target definition when supplied;
- the generated inspection image.

It deliberately separates two kinds of residual evidence:

1. `solver_rectification_vertical_epipolar_abs_px` — the residual distribution already recorded by the calibration solve across its calibration observations;
2. `pair_specific_rectified_vertical_residuals` — residuals measured from common target corners in this exact inspected image pair.

The pair-specific signed convention is:

```text
vertical_residual_b_minus_a_px = y_camera_b_rectified - y_camera_a_rectified
```

Both signed and absolute distributions are retained. No target input, failed target detection, or no common corners produces an explicit `availability: unavailable` state with null distribution statistics. The tool never substitutes fabricated zero residuals.

## Target binding

Pair-specific target evidence is accepted only when the supplied target:

- uses `bividi.calibration.stereo_target.v1`;
- is ChArUco for the current native detector path;
- has the same `target_id` and target family recorded in the calibration artifact;
- has the exact SHA-256 recorded in the calibration artifact.

A schema, identity, family, or hash mismatch is a domain/input failure.

## Policy boundary

The inspector is evidence-only.

It does not own calibration acceptance thresholds and therefore does not turn a large residual into an automatic quality `FAIL`. The machine artifact records:

```text
quality.status = EVIDENCE_ONLY_NO_THRESHOLDS
```

Exit behavior follows the frozen calibration CLI vocabulary:

- `0` — inspection completed;
- `2` — parser/input/schema/hash/dependency/decode/write/domain error;
- never `3` — the inspector has no evaluated acceptance policy.

A visually straight image or a small inspected-pair residual is not by itself calibration-promotion evidence. Promotion remains owned by the explicit stereo evidence/policy gate.

## Physical evidence boundary

Synthetic OpenCV fixtures exercise the correspondence and residual calculations in CI, but they are not measured AR0234 evidence. Physical camera ordering, capture mode, baseline comparison, measured rectification quality, and final calibration promotion remain gated on the live #35/#8 campaign.
