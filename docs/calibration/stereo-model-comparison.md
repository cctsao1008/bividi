# Stereo camera-model comparison

`bividi-calib stereo model-compare` compares solved `bividi.calibration.stereo.v1` candidates that were produced from the **same source-session evidence**.

The first supported comparison is `opencv5` versus `opencv-rational`. This is the hardware-independent first slice of #61. It does not add a fisheye solver and it does not change the default stereo solve model.

## Evidence boundary

Every candidate is validated using the existing stereo artifact validator. Candidates must match on:

- source-session SHA-256 and provenance class;
- device model/serial;
- capture mode, pixel format, image geometry, and camera A/B identities;
- target id/family/hash;
- pinhole projection convention.

The comparison output hash-binds each calibration artifact and records model-specific metrics:

- camera A/B mono RMS and maximum mono RMS;
- stereo RMS;
- vertical epipolar p95/max residual;
- valid rectified ROI fraction per camera;
- recovered baseline;
- distortion-parameter count;
- valid stereo-pair count;
- pairwise deltas between candidates.

## Selection semantics

With no explicit selection policy, the report status is:

```text
INSUFFICIENT_EVIDENCE
```

The comparator never selects the smallest training RMS automatically. An operator may nominate one of the candidate models only with `--selected-model`, a non-empty `--policy-source`, and at least one explicit gate such as:

```text
--max-mono-rms-px
--max-stereo-rms-px
--max-epipolar-p95-px
--min-valid-roi-fraction
```

All provided gates apply to the nominated candidate. Passing gates produce `PASS`; a completed explicit gate failure produces `FAIL` and exit code `3`. Input/schema/evidence mismatch and runtime/read/write errors return `2`. No numerical thresholds are owned by the tool.

## Example

```text
bividi-calib stereo model-compare \
  opencv5.json rational.json \
  --output model-comparison.json \
  --markdown model-comparison.md
```

An explicit engineering policy may be evaluated as:

```text
bividi-calib stereo model-compare \
  opencv5.json rational.json \
  --selected-model opencv-rational \
  --policy-source "camera model policy MODEL-001" \
  --max-stereo-rms-px 0.25 \
  --max-epipolar-p95-px 0.40 \
  --min-valid-roi-fraction 0.90 \
  --output model-comparison.json \
  --markdown model-comparison.md
```

These numbers are only an invocation example; they are not Bividi defaults or recommendations.

## Guardrails

- Seller nominal FOV is not evidence for a distortion model.
- Lowest global/training RMS alone is not a selection rule.
- More flexible models carry additional parameters; parameter count is reported rather than treated as an automatic penalty or benefit.
- Synthetic comparison validates tooling only. Measured AR0234 model selection remains blocked on #35/#8 physical evidence.
- Fisheye evaluation remains a separate #61 follow-up so it can be implemented and validated deliberately rather than smuggled into this comparator.
