# VIO backend evaluation and adoption gate

This review is the backend-selection checkpoint after the hardware-independent `bividi::VioBackend` boundary from #135. It records what the reviewed upstream projects actually document, pins every observation to an exact revision, and separates those facts from Bividi's engineering decision.

The machine-readable source of record is `vio/backend-evaluation-v1.json`. Validate it with:

```text
python tools/validate_vio_backend_evaluation.py
python tools/validate_vio_backend_evaluation.py --self-test
```

## Result

**No VIO backend is adopted.** The review nominates **Kimera-VIO only as the first Linux offline integration spike**. Basalt remains the alternate permissive candidate. OpenVINS, VINS-Fusion, and ORB-SLAM3 are retained as reference implementations while Bividi has no explicit copyleft/project-license decision.

This is an engineering governance decision, not a statement that one estimator is more accurate than another.

## Source-derived findings

### Kimera-VIO — first spike candidate

Pinned revision: `ce8c59b7b273ab5ac29db7e5572e1623760e19c7`.

The upstream README describes Kimera-VIO as a **Stereo + IMU** VIO pipeline and says it was tested on Ubuntu 20.04. It lists GTSAM, OpenCV, OpenGV, glog/gflags, DBoW2, and Kimera-RPGO among its prerequisites. The pinned CMake file uses C++17 and builds `kimera_vio` as a shared library. ROS is supplied by a separate wrapper rather than being required by the core library. The repository is BSD-2-Clause.

The same source set does **not** establish native Windows support. Bividi therefore records Windows as `unverified`, not supported or unsupported by inference. The dependency graph is also materially heavier than `bividi_vio`, and its third-party license closure has not been reviewed here.

### Basalt — alternate permissive candidate

Pinned mirror revision: `0f3b2b52c807f70ff4e2973ce253c73329eea7bc`.

Basalt documents camera/IMU calibration plus visual-inertial odometry and mapping. Its README records BSD-3-Clause licensing and current CMake/vcpkg installation. The pinned CMake uses C++17 and can build the Basalt core as a shared or static library.

Unlike Kimera's unverified Windows state, Basalt's current CMake explicitly warns that **only Linux and macOS are currently supported**. Its vcpkg manifest also pulls a broad dependency set including OpenCV, TBB, Boost, Pangolin, OpenGV, rosbag, realsense2, and basalt-headers. That makes it valuable as an alternate spike but a worse immediate fit for Bividi's cross-platform native baseline.

### OpenVINS — high-value reference, not current integration candidate

Pinned revision: `69488123ed9362dd44b6f28e7f4680abbff1442b`.

OpenVINS documents synchronized stereo/binocular visual tracking, camera-to-IMU extrinsic calibration, camera-to-IMU time-offset calibration, and a ROS-free build path. Its pinned CMake allows ROS to be disabled and depends primarily on Eigen, OpenCV, Boost, and Ceres. This is a strong technical reference for Bividi's #47/#135 semantics.

The upstream project is GPL-3.0. Bividi currently has no declared repository license and no explicit copyleft integration decision, so this review keeps OpenVINS `reference_only`. That is a project-governance guardrail, not legal advice.

### VINS-Fusion — reference only

Pinned revision: `be55a937a57436548ddfb1bd324bc1e9a9e828e0`.

Its README explicitly supports stereo cameras + IMU and online spatial/temporal camera-IMU calibration, and lists pinhole, Mei, and equidistant camera models. The documented build path is Ubuntu 16.04/18.04 with ROS Kinetic/Melodic and catkin. The source is GPLv3 and the pinned master revision is from 2021, so it is retained as a reference rather than the first Bividi integration spike.

### ORB-SLAM3 — useful visual-inertial reference, beyond first #46 scope

Pinned revision: `4452a3c4ab75b1cde34e5505a36ec3f9edcdc4c4`.

ORB-SLAM3 documents stereo-inertial operation with pinhole and fisheye cameras, C++11, and a standalone `libORB_SLAM3.so`; ROS examples are optional. Its README also documents GPLv3 and tested Ubuntu 16.04/18.04. It is a full visual-inertial **SLAM/multi-map** system, which is deliberately broader than #46's first VIO-only phase. It therefore remains reference-only in this review.

## Why Kimera first, but not selected

The first spike is meant to answer integration questions, not accuracy questions. Kimera combines the properties currently most useful for that experiment: permissive upstream license, explicit stereo+IMU focus, C++17, and a core library surface that is not intrinsically ROS-bound. The spike must still prove all of the hard parts Bividi cares about:

- mapping #8 stereo intrinsics/extrinsics into the backend without model invention;
- mapping #47 IMU noise/extrinsics/time semantics without hidden defaults;
- feeding #135 device timestamps and reset/reinitialize transitions correctly;
- converting backend output into `PoseObservation` with the frozen frame convention;
- measuring build burden, runtime, initialization, loss/recovery, and CPU on a named host;
- deciding what Windows means operationally: native port, isolated Linux process, or rejection.

Until those are measured, `decision.adoption_status` stays `NOT_ADOPTED` and every adoption gate stays open or hardware-blocked.

## Next slice

The next implementation should be a **pinned Kimera-VIO offline adapter spike on Linux** behind `bividi::VioBackend`, with no changes to `SensorObservation` or the #135 public contract. It should first prove deterministic input/config translation and reset/output semantics on a known offline dataset; measured AR0234 accuracy remains a later hardware phase after #35/#8/#47 evidence is available.
