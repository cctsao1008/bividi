# Stereo fisheye candidate evaluation

`bividi-calib stereo fisheye-evaluate` evaluates an OpenCV fisheye model against the same hash-bound stereo-session evidence used by the #8 pinhole workbench.

It emits `bividi.calibration.stereo_fisheye_candidate.v1`. This is deliberately a **candidate artifact**, not `bividi.calibration.stereo.v1` and not a promoted measured calibration.

## Why a separate schema

The durable `stereo.v1` contract is pinhole-oriented. It requires pinhole projection semantics, classical `E/F`, `pinhole_fov_deg`, and OpenCV pinhole valid-ROI fields. Copying OpenCV fisheye results into those fields would make the artifact look compatible while changing their mathematical meaning.

The fisheye candidate therefore records only evidence that has a direct fisheye interpretation:

- source-session and target SHA-256 bindings;
- device/capture/camera A/B identity;
- `projection=fisheye`, `distortion=opencv-fisheye`;
- per-camera `K` and four fisheye distortion coefficients;
- mono RMS and per-view reprojection RMS;
- stereo `R/T`, baseline and stereo RMS;
- fisheye `R1/R2/P1/P2/Q` rectification products;
- vertical rectified epipolar residual distribution;
- inverse rectification-map valid fraction for each camera.

It intentionally does **not** contain classical pinhole pixel-space `E/F`, `pinhole_fov_deg`, or pinhole `validROI` fields.

## OpenCV solve path

The evaluator uses:

```text
cv2.fisheye.calibrate
cv2.fisheye.stereoCalibrate (fixed intrinsics)
cv2.fisheye.stereoRectify
cv2.fisheye.undistortPoints
cv2.fisheye.initUndistortRectifyMap
```

OpenCV/NumPy remain optional dependencies. Contract validation and CLI discovery do not import them until a fisheye solve or OpenCV self-test is requested.

## Model comparison

`bividi-calib stereo model-compare` accepts both pinhole `stereo.v1` artifacts and the fisheye candidate schema when they are bound to identical source evidence.

Common metrics include mono/stereo RMS, epipolar residuals, baseline and distortion-parameter count. Valid-area evidence is also reported, but its measurement method is explicit:

- pinhole: `pinhole_valid_roi_area_fraction`;
- fisheye: `fisheye_inverse_map_in_source_domain_fraction`.

Because those are not identical estimators, their pairwise delta is left `null` across method families instead of pretending the numbers are directly equivalent. An explicit `--min-valid-area-fraction` policy may still evaluate the selected candidate using its recorded method; the legacy `--min-valid-roi-fraction` gate remains pinhole-only.

## Guardrails

Synthetic success proves the implementation and metric plumbing only. It does not choose a lens model for the delivered AR0234 module. Measured model selection still requires the #35/#8 physical capture gate, intentionally diverse calibration evidence, and an explicit named engineering policy. Lowest training RMS alone is not a model-selection rule.
