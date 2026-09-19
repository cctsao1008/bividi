# Pinned Kimera-VIO translation boundary

This layer freezes how Bividi's hardware-independent `VioPacket` and #8/#47 calibration artifacts map toward the exact upstream Kimera-VIO revision selected by the backend review:

```text
MIT-SPARK/Kimera-VIO@ce8c59b7b273ab5ac29db7e5572e1623760e19c7
```

It is **not** a Kimera backend implementation or adoption decision. Normal Bividi CI still has no Kimera, GTSAM, or extra OpenCV dependency because of this layer.

## Feed contract

`bividi::translate_kimera_feed()` accepts only a backend-ready #135 `VioPacket`. The translation preserves the source sequence as Kimera `FrameId`, continuity epoch, left/right zero-copy `ImageView` plus `FrameLease`, and IMU ordering as accel xyz followed by gyro xyz.

Device timestamps may be microseconds or nanoseconds. They are converted exactly to signed nanoseconds and rejected on overflow. Host receive time is never consulted. IMU timestamps must remain strictly increasing after conversion.

A #135 `reinitialize` directive becomes `recreate_pipeline_before_feed`. `reset_before_next`, rejected packets, missing source sequence, missing image lifetime, and unrepresentable timestamps are not feedable. This is deliberate because the pinned public API exposes pipeline shutdown/lifecycle but no reviewed hot-reset contract equivalent to #135.

## Calibration/config plan

`tools/prepare_kimera_vio_translation.py` consumes exactly three validated artifacts:

```text
bividi.calibration.stereo.v1
bividi.calibration.imu.v1
bividi.calibration.camera_imu.v1
```

The resulting `bividi.vio.kimera_translation_plan.v1` hash-binds all three inputs and records exact upstream source/API provenance.

The matrix notation in the plan is:

```text
T_X_from_Y * p_Y = p_X
```

#47 stores `T_camera_a_from_body`, where Bividi's VIO body is the calibrated IMU frame. Kimera `T_BS` is `body_Pose_cam`, so:

```text
T_body_from_camera_a = inverse(T_camera_a_from_body)
```

#8 stores `T_camera_b_from_camera_a` through `R_camera_b_from_camera_a` and `T_camera_b_from_camera_a_m`. Therefore:

```text
T_body_from_camera_b =
    T_body_from_camera_a * inverse(T_camera_b_from_camera_a)
```

The IMU `T_BS` is identity because the calibrated IMU frame is the body frame.

### Camera models

Promoted `stereo.v1` pinhole `opencv5` and `opencv-rational` candidates map to Kimera's pinhole `radtan` vocabulary while preserving the full OpenCV coefficient vector. The pinned `CameraParams` implementation accepts a radtan coefficient vector with at least four coefficients; OpenCV rational output may contain 8, 12, or 14 coefficients and is not truncated.

The separate `stereo_fisheye_candidate.v1` evaluation artifact is intentionally **not** accepted here because it is not a promoted #8 `stereo.v1` calibration.

Kimera `CameraParams` also requires `rate_hz`, but `stereo.v1` does not carry camera rate. The plan marks that field unresolved rather than inventing a default; the later runtime spike must supply it from an explicit runtime/config source.

### IMU parameters

The plan requires all four #47 noise terms and an explicit sample-rate value. Rate preference is measured rate, then timing effective rate, then explicit nominal rate. The selected source field is recorded. Missing noise/rate evidence blocks plan generation; no upstream/example defaults are reused.

### Time offset sign

Bividi #47 freezes:

```text
t_imu_s = t_camera_reference_s + offset_s
```

The pinned Kimera `TimeAlignerBase` freezes the same relation:

```text
t_imu = t_cam + imu_shift
```

and `DataProviderModule::setImuTimeShift(double)` accepts seconds before converting internally to nanoseconds. Therefore the mapping is direct and same-sign:

```text
Kimera imu_time_shift = Bividi offset_s
```

No negation, absolute value, or guessed convention is allowed. The camera time reference (`exposure_start`, `exposure_midpoint`, or `exposure_end`) is also preserved in the machine plan.

## Upstream evidence used

The pinned mapping records these upstream sources/symbols, among others: `common/vio_types.h` (`Timestamp`, `FrameId`, `ImuAccGyr`), `CameraParams.cpp`, `kalibr_params_to_kimera_vio_params.py`, `TimeAlignerBase.h`, and `DataProviderModule.h`. Floating `master` is not translation evidence.

## Remaining gate

This issue deliberately stops before compiling/linking Kimera. A separate follow-up must build the exact pinned dependency closure on Linux, render the remaining runtime-only configuration (including camera rate and explicit Frontend/Backend/LCD/Display policy inputs), instantiate/recreate the pipeline, and run offline synthetic/replay data. Windows feasibility and measured AR0234 accuracy remain separate gates under #46.
