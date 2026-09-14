# Characterization

This directory contains repeatable characterization procedures and, later, measured results for the active **stereo AR0234 + IMU** reference device.

Current live-hardware work is owned by Issue #35, with device/source evidence tracked in #32.

Characterization must keep these layers distinct:

```text
vendor claim
!= documented interface behavior
!= offline sample behavior
!= measured live hardware behavior
```

The current plans focus on:

- host-visible USB/UVC/vendor-SDK behavior;
- actual supported modes and sustained capture;
- transport geometry and camera A/B → physical left/right mapping;
- timestamp continuity, IMU cadence, drops, duplicates, jitter, and recovery;
- trigger/synchronization measurements when the hardware setup permits them.

Historical candidate-camera characterization plans are not maintained in the current tree; they remain available through Git history and Issues.