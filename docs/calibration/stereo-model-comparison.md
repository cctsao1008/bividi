# Stereo camera-model comparison

`bividi-calib stereo model-compare` compares camera-model candidates produced from the **same source-session evidence**.

Supported candidates are:

- `opencv5` and `opencv-rational` from `bividi.calibration.stereo.v1`;
- `opencv-fisheye` from `bividi.calibration.stereo_fisheye_candidate.v1`.

The fisheye candidate intentionally uses a separate schema so pinhole-only `E/F`, FOV and ROI semantics are not fabricated.

## Evidence boundary

Every candidate is validated by its owning schema validator. Candidates must match on:

- source-session SHA-256 and provenance class;
- device model/serial;
- capture mode, pixel format, image geometry, and camera A/B identities;
- target id/family/hash.

Projection/model identity is **not** part of the evidence identity because model comparison is specifically testing different mathematical models against the same observations.

The comparison output hash-binds each candidate and records:

- camera A/B mono RMS and maximum mono RMS;
- stereo RMS;
- vertical epipolar p95/max residual;
- recovered baseline;
- distortion-parameter count;
- valid stereo-pair count;
- valid-area evidence and its measurement method;
- pairwise deltas for metrics with common semantics.

Valid-area methods remain explicit:

- pinhole: `pinhole_valid_roi_area_fraction`;
- fisheye: `fisheye_inverse_map_in_source_domain_fraction`.

Those are not treated as numerically equivalent estimators. Their pairwise delta is therefore `null` when the methods differ.

## Selection semantics

With no explicit selection policy, the report status is:

```text
INSUFFICIENT_EVIDENCE
```

The comparator never selects the smallest training RMS automatically. An operator may nominate one candidate only with `--selected-model`, a non-empty `--policy-source`, and at least one explicit gate:

```text
--max-mono-rms-px
--max-stereo-rms-px
--max-epipolar-p95-px
--min-valid-area-fraction
```

The legacy `--min-valid-roi-fraction` gate is retained for pinhole candidates only. Using it to nominate a fisheye candidate is a domain error rather than silently changing its meaning.

All provided gates apply to the nominated candidate. Passing gates produce `PASS`; a completed explicit gate failure produces `FAIL` and exit code `3`. Input/schema/evidence mismatch and runtime/read/write errors return `2`. No numerical thresholds are owned by the tool.

## Example

```text
bividi-calib stereo model-compare \
  opencv5.json rational.json fisheye-candidate.json \
  --output model-comparison.json \
  --markdown model-comparison.md
```

An explicit engineering policy may be evaluated as:

```text
bividi-calib stereo model-compare \
  opencv5.json rational.json fisheye-candidate.json \
  --selected-model opencv-fisheye \
  --policy-source "camera model policy MODEL-001" \
  --max-stereo-rms-px 0.25 \
  --max-epipolar-p95-px 0.40 \
  --min-valid-area-fraction 0.90 \
  --output model-comparison.json \
  --markdown model-comparison.md
```

These numbers are invocation examples only; they are not Bividi defaults or recommendations.

## Guardrails

- Seller nominal FOV is not evidence for a distortion model.
- Lowest global/training RMS alone is not a selection rule.
- More flexible models carry additional parameters; parameter count is reported rather than treated as an automatic penalty or benefit.
- Metrics with different measurement semantics are labeled rather than silently equated.
- Synthetic comparison validates tooling only. Measured AR0234 model selection remains blocked on #35/#8 physical evidence.
