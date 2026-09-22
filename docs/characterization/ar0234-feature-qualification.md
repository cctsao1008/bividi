# AR0234 Feature-First Physical Qualification

Owner: Issue #35  
Reference device: DECXIN AR0234 stereo + ICM-42688-P

## Why this exists

Long-duration stability evidence is useful only after the basic functional surface is known to work. This workflow therefore runs **feature qualification first** and leaves 10-minute / one-hour soak testing as a separate later phase.

The automated entry point is:

```text
python tools/run_ar0234_feature_qualification.py
```

It writes one session directory containing:

```text
feature-results.json
report.md
*.stdout.log
*.stderr.log
MJPEG forensic packets / scanner logs
IMU trace artifacts
calibration-session artifacts
recovery event artifacts
```

The report always contains the full matrix. A test that cannot be automated is shown as `PENDING`, not silently promoted to PASS.

## Functional matrix

### Automated

```text
A00 probe / provenance / advertised modes
A01 MJPEG raw acquisition + source sequence continuity
A02 MJPEG compressed JPEG / DRI / restart-marker integrity
A03 MJPEG bounded decoupled acquisition + decode
A04 YUYV raw acquisition + exact 4000x1200x2 payload geometry
A05 YUYV -> BGR -> DECXIN metadata/stereo decode
A06 IMU recorder + sample validity + timestamp continuity
A07 calibration recorder stereo PNG + frames/IMU artifact generation
A08 VideoStop/VideoStart lifecycle recovery
A09 SDK stream destroy/reopen recovery
```

### Operator-assisted / physical

```text
M01 camera_a / camera_b physical mapping and image orientation
M02 exposure control set/readback and visible response
M03 gain control set/readback and visible response
M04 trigger control/readback and external-trigger behavior where applicable
M05 NoriCaptureSession preview + SensorObservation live boundary
M06 engineering viewer live preview and controls
M07 web engineering console live preview and controls
M08 actual USB/device/audio enumeration
M09 physical USB unplug/replug outcome
M10 hardware synchronization electrical/timing measurement
M11 100-degree SKU optics / calibration evidence hand-off
```

### Deferred stability phase

```text
S01 10-minute sustained run
S02 one-hour soak / RSS stability
```

S01/S02 are deliberately not part of the default feature-first execution order.

## Windows example

From the repository root after the Nori+OpenCV build is available:

```powershell
python .\tools\run_ar0234_feature_qualification.py `
  --build-dir .\build-nori-opencv\Release `
  --device 0 `
  --continue-on-failure
```

The runner probes modes first. The delivered specimen is currently expected to expose `4000x1200` MJPEG and YUYV modes, but mode indices are discovered from probe output rather than hard-coded. They can be overridden explicitly:

```powershell
python .\tools\run_ar0234_feature_qualification.py `
  --build-dir .\build-nori-opencv\Release `
  --device 0 `
  --mjpeg-mode 0 `
  --yuyv-mode 1
```

Run only selected automated tests while debugging:

```powershell
python .\tools\run_ar0234_feature_qualification.py `
  --build-dir .\build-nori-opencv\Release `
  --tests A04,A05
```

List the full matrix without touching hardware:

```powershell
python .\tools\run_ar0234_feature_qualification.py --list-tests
```

Review the exact commands and artifact paths without running them:

```powershell
python .\tools\run_ar0234_feature_qualification.py `
  --build-dir .\build-nori-opencv\Release `
  --dry-run
```

## Recording physical/manual checks

The runner creates `report.md` with M01..M11 as `PENDING`. Record them against the same session directory:

```powershell
python .\tools\record_ar0234_manual_check.py `
  .\artifacts\physical\nori\feature-qualification\<SESSION> `
  --interactive
```

Or update one item explicitly. M01 was physically verified on the delivered specimen by occluding one lens at a time while viewing the live Nori preview. To avoid left/right perspective ambiguity, record the mapping in observer-facing terms:

```powershell
python .\tools\record_ar0234_manual_check.py `
  .\artifacts\physical\nori\feature-qualification\<SESSION> `
  --id M01 `
  --status pass `
  --note "observer facing lens side: front-view-left lens -> camera_a; front-view-right lens -> camera_b"
```

This means that if a later stereo convention defines rig-left/rig-right from the cameras' own forward-looking direction, the left/right labels are reversed relative to observer-facing front view. Keep `camera_a` / `camera_b` as the transport identities until that coordinate convention is explicitly frozen.

Each update refreshes `report.md`.

## Pass semantics

`Functional overall = PASS` requires:

```text
all A00..A09 automated checks PASS
all M01..M11 operator/physical checks PASS or explicitly N/A
```

`BLOCKED` and `PENDING` keep the overall result `INCOMPLETE`. Any explicit `FAIL` makes the functional result `FAIL`.

The stability rows S01/S02 remain `DEFERRED` and do not affect the functional verdict until the project intentionally moves to the endurance phase.

## Important boundaries

- A bounded functional PASS is not a long-run reliability claim.
- Host arrival timing is not a substitute for embedded exposure/IMU device timing.
- `camera_a` / `camera_b` remain the transport identities until M01 plus calibration-coordinate conventions establish final stereo left/right naming.
- A08 SDK VideoStop/VideoStart and A09 SDK reopen are not substitutes for M09 physical USB unplug/replug.
- M10 requires actual electrical/timing measurement; software consistency alone is not hardware-sync accuracy evidence.

Related: #35, `ar0234-qualification-protocol.md`, `nori-live-characterization.md`.
