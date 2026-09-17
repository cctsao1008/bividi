# Kalibr Camera↔IMU Result Import and Temporal Review

Owner: Issue #47  
Upstream: `bividi.calibration.kalibr_dynamic_session.v1` + external Kalibr solve  
Output: candidate `bividi.calibration.camera_imu.v1` + import/review evidence  
Status: hardware-independent importer/review tooling implemented; physical AR0234 solve pending

## Purpose

A Kalibr solve is external evidence, not automatically a Bividi calibration artifact. This layer makes the import/review boundary explicit:

```text
provenance-bound dynamic session
        +
Kalibr *-camchain-imucam.yaml
        +
Kalibr *-results-imucam.txt
            |
            +--> import_kalibr_camera_imu.py
            |       validated camera↔IMU artifact candidate
            |       + import sidecar
            |
            +--> analyze_kalibr_solver_quality.py
            |       normalized + physical residual evidence
            |
            +--> review_camera_imu_time_offset.py
                    protocol/timestamp evidence review
                        |
                        +--> compare_camera_imu_calibrations.py
                                repeated-session consistency
                                    ↓
                         manual/requirements-based promotion decision
```

## Exact Kalibr fields

At pinned revision `1f60227442d25e36365ef5f72cd80b9666d73467`, Kalibr's camera-chain configuration stores:

```text
camN.T_cam_imu
camN.timeshift_cam_imu
```

`T_cam_imu` is the transform from `imu0` coordinates into the selected camera coordinates. The time-shift convention is:

```text
t_imu = t_cam + timeshift_cam_imu
```

This matches Bividi's v1 numeric sign only when the same camera timestamp semantic is preserved.

The same pinned Kalibr source writes solver residual statistics into `*-results-imucam.txt` through `IccUtil.py::printErrorStatistics`. Bividi parses those statistics separately rather than pretending the YAML transform alone proves solver quality.

## Import

Example:

```bash
python tools/import_kalibr_camera_imu.py \
  ar0234_kalibr_001/session.json \
  kalibr_dynamic-camchain-imucam.yaml \
  --camera cam0 \
  --camera-axes "+X right, +Y down, +Z forward; verified for this camera/Kalibr convention" \
  --calibration-id ar0234-camA-imu-001 \
  --solver-report kalibr_dynamic-results-imucam.txt \
  --external-container "<pinned image digest>" \
  --output ar0234-camA-imu-001.json
```

The importer deliberately requires an explicit `--camera-axes` description. It does not infer physical left/right identity and keeps the dynamic-session mapping:

```text
cam0 → camera_a
cam1 → camera_b
```

For a different Bividi frame name, pass `--camera-frame` explicitly.

The importer verifies:

```text
dynamic session schema
session source SHA-256 values
selected camera mapping
timestamp semantic + sign definition
Kalibr result T_cam_imu shape/numeric values
Kalibr timeshift numeric value
IMU calibration source hash/device identity
final Bividi camera-IMU artifact invariants
```

It writes an import sidecar recording the exact dynamic-session hash, Kalibr-result hash, optional solver-report hash, Kalibr revision/container, selected camera, transform/time definitions, and candidate status.

A valid import is still labelled for review. The YAML transform alone does not provide enough quality evidence to claim an accurate physical calibration.

## Solver quality evidence

Analyze the exact Kalibr text report against the same prepared dynamic session:

```bash
python tools/analyze_kalibr_solver_quality.py \
  ar0234_kalibr_001/session.json \
  kalibr_dynamic-results-imucam.txt \
  --output-prefix ar0234_kalibr_001/solver-quality
```

The tool preserves:

```text
Normalized Residuals
  cam0/cam1 reprojection
  imu0 gyroscope
  imu0 accelerometer

Residuals
  reprojection [px]
  gyroscope [rad/s]
  accelerometer [m/s^2]
```

with Kalibr's printed mean, median, population standard deviation, plus a derived residual-norm RMS. The dynamic-session and text-report SHA-256 values are retained in `bividi.calibration.kalibr_solver_quality.v1`.

For the Bividi stereo workflow, missing expected residual evidence or `no corners` on `cam0`/`cam1` is a structural failure. Otherwise, with no explicit lab/product limits, status remains:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

See `docs/calibration/kalibr-solver-quality-gate.md` for the exact pinned source contract and optional requirement-based gates.

## Temporal evidence review

`tools/review_camera_imu_time_offset.py` uses the exact raw dynamic-session IMU trace hash-bound by `session.json`; it does not accept host arrival as sensor time.

The imported Kalibr offset is applied to the same camera timestamp semantic used during export:

```text
shifted camera time = camera_reference + Kalibr offset
```

For every camera frame the tool then reports nearest-IMU sampling geometry before and after applying the shift:

```text
signed IMU - camera delta
absolute nearest delta
P50 / P95 / P99 / max
IMU sample-interval distribution
exposure-duration distribution
```

Example evidence-only review:

```bash
python tools/review_camera_imu_time_offset.py \
  ar0234_kalibr_001/session.json \
  ar0234-camA-imu-001.json \
  --output-prefix ar0234-camA-imu-001
```

This produces:

```text
ar0234-camA-imu-001.time-review.json
ar0234-camA-imu-001.time-review.md
```

By default the status is:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

Optional explicit gates are available only when a requirement or measured baseline justifies them:

```bash
--max-abs-shift-us <LIMIT>
--max-shifted-nearest-p95-us <LIMIT>
```

No vendor synchronization claim is silently used as a pass/fail threshold.

## Important interpretation boundary

Nearest-sample timing is **not** an independent estimator of camera↔IMU temporal offset.

At a finite IMU sample rate, multiple offsets separated by approximately one sample period can produce similar nearest-sample residuals. Therefore:

```text
small nearest residual after shift
    !=
proof that the Kalibr offset is physically correct
```

Likewise:

```text
small Kalibr solver residuals
    !=
proof that the physical calibration is accurate
```

The solver-quality report measures optimizer fit. Temporal review catches gross clock/sign/semantic mistakes. Repeatability measures cross-session stability. These evidence classes remain separate.

The temporal review is intended to catch gross mistakes such as:

```text
wrong sign
seconds vs microseconds
ES vs EE mismatch
wrong session/result pairing
wrong camera mapping
large unexplained temporal disagreement
```

Final acceptance still needs Kalibr solver quality, target detection quality, motion excitation, repeated-session stability, protocol-level timing evidence, and downstream VIO behavior.

## Guardrails

- A successful Kalibr optimizer run is not automatic Bividi promotion.
- `T_cam_imu` direction is preserved explicitly as IMU → camera.
- `timeshift_cam_imu` is imported only with the dynamic session's exact camera timestamp semantic.
- Imported artifacts remain tied to the dynamic-session SHA-256.
- Kalibr result/report hashes are retained in the import sidecar/review notes.
- Solver residual quality is retained as its own hash-bound evidence artifact rather than collapsed into an unsupported accuracy claim.
- Camera axes are operator-declared/verified, never silently invented.
- Camera A/B are not renamed left/right without #35 physical evidence.
- No default solver or temporal tolerance is invented.

Related: #8, #35, #47, #46.