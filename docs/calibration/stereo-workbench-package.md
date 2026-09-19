# Package-native stereo calibration workbench

Issue #127 moves the remaining #8 stereo calibration workbench from source-tree-only `tools/` modules into the installed `bividi.calibration` package.

This is a packaging/routing migration. It does **not** turn synthetic/offline calibration into measured AR0234 evidence, does not establish physical left/right camera identity, and does not complete the live calibration gate in #8. Those claims still depend on #35 physical-device evidence.

## Installed command surface

The existing commands keep their CLI names and arguments:

```text
bividi-calib stereo target ...
bividi-calib stereo session ...
bividi-calib stereo session-recorder ...
bividi-calib stereo inspect ...
bividi-calib stereo solve ...
bividi-calib stereo validate ...
bividi-calib stereo rectify ...
```

All seven now route to `bividi.calibration.stereo_workbench_command`. They no longer require `--source-root`, `BIVIDI_SOURCE_ROOT`, or a repository checkout.

The historical files remain under `tools/` as thin compatibility re-exports/entry points. The algorithms live only in the installed package modules:

```text
bividi.calibration.stereo_calibration_common
bividi.calibration.stereo_calibration_recorder
bividi.calibration.stereo_calibration_solve
bividi.calibration.stereo_calibration_workbench
```

The implementation filenames are intentionally retained because existing v1 artifacts record `Path(__file__).name` as provenance.

## Frozen v1 artifacts

The migration preserves:

```text
bividi.calibration.stereo_target.v1
bividi.calibration.stereo_session.v1
bividi.calibration.stereo_dataset_quality.v1
bividi.calibration.stereo.v1
```

Tool version remains `1` where the historical artifacts already recorded a version.

`camera_a` and `camera_b` remain transport-neutral identities. The package migration does not rename them to left/right and does not manufacture mapping evidence.

## Dependency boundary

The base package remains dependency-light. OpenCV and NumPy are imported only by commands that actually need computer vision operations:

- ChArUco rendering/detection;
- dataset image inspection;
- intrinsic/stereo solving;
- rectification rendering;
- the optional OpenCV synthetic solver self-test.

Target/session metadata, recorder import, artifact validation, and the dependency-free self-test do not require OpenCV.

ROS, Kalibr, Nori, and vendor SDKs are not dependencies of this workbench package boundary.

## Quality ownership and process exits

The leaf implementations continue to own their numerical gates. The package router adds no default thresholds.

`inspect` can write `bividi.calibration.stereo_dataset_quality.v1` with:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
PASS
FAIL
```

`solve` stores the same three-state quality disposition under `artifact.quality.status`.

A gated result requires the leaf's explicit `--policy-source`. After the leaf has successfully produced a structurally valid result, the package command adapter maps an explicit `FAIL` to the frozen evaluated-fail process exit:

```text
0  successful command / PASS / evidence-only
2  usage, input, schema, dependency, runtime, read/write, or malformed artifact error
3  completed explicit inspect/solve policy FAIL
```

`validate` is structural validation. A malformed or incompatible calibration artifact is an input/domain error (`2`), not an evaluated quality-policy FAIL (`3`).

`rectify` is an inspection/presentation product and does not create an acceptance decision.

## Provenance preservation

Historical provenance basenames remain stable:

- target/session/dataset-quality artifacts: `stereo_calibration_common.py`;
- recorder-derived measured session: `stereo_calibration_recorder.py`;
- solved calibration artifact: `stereo_calibration_solve.py`.

The source-tree wrappers do not replace those identities with wrapper paths.

## Relationship to physical calibration

The package now makes the complete workbench installable, but the evidence hierarchy is unchanged:

```text
package migration != measured calibration
synthetic solve != AR0234 calibration
artifact validity != physical correctness
camera_a/camera_b != left/right mapping
```

Measured #8 promotion remains blocked until #35 verifies the delivered hardware path, physical camera ordering, capture mode, timing/synchronization behavior, and a real diverse calibration session is acquired and reviewed.
