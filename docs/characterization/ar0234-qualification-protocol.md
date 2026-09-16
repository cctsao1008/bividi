# AR0234 Physical Qualification Protocol

Owner: Issue #35  
Reference device: DECXIN AR0234 stereo + ICM-42688-P  
Status: procedure ready; physical execution pending delivered hardware

## Purpose

This protocol turns the live Nori path into a repeatable sensor-qualification sequence. It separates software restart tests from actual USB/power faults and produces artifacts that can be compared across firmware, host OS, transport mode, backend changes, and code revisions.

The principle is:

```text
probe first
→ establish a clean baseline
→ extend duration
→ inject controlled software faults
→ inject physical transport/power faults
→ compare evidence
```

A single successful preview is not qualification evidence.

## Required tools

```text
bividi-nori-probe
bividi-nori-characterize
tools/compare_nori_characterization.py
```

Optional host-native tools remain useful for independent USB/UVC evidence, as described in `usb-uvc-test-plan.md`.

## Session naming

Use a stable prefix that identifies enough context to compare runs later. A recommended form is:

```text
YYYYMMDD_<host>_<backend>_<transport>_<purpose>_<revision>
```

Example:

```text
20260920_win11_nori_mjpeg_baseline60s_a1
```

Keep the resulting JSON, frame CSV, RSS CSV, and event CSV together. Large video captures stay outside normal Git history; retain hashes/external references when needed.

## Q0 — Probe and provenance

Before every qualification campaign:

```bash
bividi-nori-probe
```

Record the actual device/mode index rather than assuming `0/0`.

Preserve at least:

```text
VID / PID
serial
SDK version
device type
ISP version
FPGA version
advertised modes
selected mode
host OS/version
Bividi revision
```

A firmware or SDK change is not noise; it is provenance and should remain visible in comparisons.

## Q1 — 60-second baseline smoke

Goal: prove basic decode/continuity without intentional disturbances.

```bash
bividi-nori-characterize \
  --device <DEVICE> \
  --mode <MODE> \
  --duration-s 60 \
  --warmup-frames 30 \
  --output-prefix <PREFIX>_baseline60s
```

Review:

- characterizer assessment;
- measured FPS;
- spontaneous drops/duplicates/out-of-order sequence observations;
- timeout/decode-error counts and streaks;
- ES/EE and IMU interval distributions;
- returned mode versus selected mode;
- initial RSS behavior.

Do not proceed to a long soak if basic decode is unstable.

## Q2 — 10-minute sustained run

Goal: expose intermittent transport/timing problems that do not appear in a 60-second smoke run.

```bash
bividi-nori-characterize \
  --device <DEVICE> \
  --mode <MODE> \
  --duration-s 600 \
  --warmup-frames 30 \
  --rss-sample-ms 1000 \
  --output-prefix <PREFIX>_baseline10m
```

Compare against Q1 for continuity, FPS, p99 timing, and RSS trend. The longer run is expected to provide stronger evidence, not necessarily numerically identical percentiles.

## Q3 — One-hour soak / memory stability

Goal: collect long-run timing and process-memory evidence with no intentional fault injection.

```bash
bividi-nori-characterize \
  --device <DEVICE> \
  --mode <MODE> \
  --duration-s 3600 \
  --warmup-frames 30 \
  --rss-sample-ms 1000 \
  --output-prefix <PREFIX>_soak1h
```

Review both RSS distribution and `growth_mib_per_hour`. RSS slope is descriptive evidence, not an automatic leak verdict. Investigate a sustained positive trend together with the raw RSS trace, allocator behavior, buffering, and steady-state plateau behavior before calling it a leak.

## Q4 — Controlled video stop/start recovery

Goal: verify stream lifecycle recovery without destroying the SDK stream object.

Example:

```bash
bividi-nori-characterize \
  --device <DEVICE> \
  --mode <MODE> \
  --duration-s 600 \
  --stop-start-every-frames <INTERVAL> \
  --stop-start-pause-ms 250 \
  --recovery-timeout-ms 10000 \
  --output-prefix <PREFIX>_stopstart
```

The tool creates a new continuity epoch around each intentional interruption. Planned downtime is therefore evaluated as a recovery event rather than falsely counted as a spontaneous sequence drop.

Check:

```text
operation_succeeded
recovered
recovery_ms
pre/post sequence
pre/post ES raw counter
sequence reset observed
device-time reset observed
```

## Q5 — SDK stream destroy/reopen recovery

Goal: exercise a stronger software reconnect while the physical USB device remains attached.

```bash
bividi-nori-characterize \
  --device <DEVICE> \
  --mode <MODE> \
  --duration-s 600 \
  --reconnect-every-frames <INTERVAL> \
  --reconnect-pause-ms 500 \
  --recovery-timeout-ms 10000 \
  --output-prefix <PREFIX>_sdk_reconnect
```

Important boundary:

```text
SDK stream destroy/reopen
!= physical USB unplug/replug
!= hub reset
!= device power cycle
```

Q5 proves only the first behavior.

## Q6 — Physical USB unplug/replug

Goal: verify behavior when the actual transport disappears and returns.

This is currently a **manual/external fault procedure**. Do not pretend the in-process SDK reconnect option is equivalent.

Procedure:

1. begin a normal long-running capture and record the exact wall-clock time / frame region;
2. physically unplug the camera USB connection;
3. record the application's observed error/timeout behavior;
4. reconnect the same device;
5. determine whether the existing process can recover, requires an explicit reopen, or must be restarted;
6. run a fresh post-reconnect characterization session;
7. retain OS USB/device-manager evidence if enumeration identity changed.

Until an explicit backend state machine supports true hot-unplug recovery, report the actual outcome rather than forcing the test to look successful.

## Q7 — Hub reset / bus reset / power-cycle

These are optional stronger physical-fault tests when the lab setup can perform them safely and reproducibly.

Keep them distinct:

```text
USB logical reset
powered-hub port reset
USB bus/controller reset
device power cycle
host suspend/resume
```

Each mechanism may exercise a different host/firmware path and therefore deserves a separate session label.

## Regression comparison

Compare any two v2 summary JSON files with:

```bash
python tools/compare_nori_characterization.py \
  baseline.json candidate.json \
  --markdown-out comparison.md \
  --json-out comparison.json
```

Default behavior deliberately avoids invented performance limits. It checks structural comparability, candidate hard failures, and correctness-counter regressions while presenting timing/FPS/recovery/RSS deltas as evidence.

If a project or experiment has an explicit budget, turn it into a gate. Example only:

```bash
python tools/compare_nori_characterization.py \
  baseline.json candidate.json \
  --max-fps-drop-pct <BUDGET> \
  --max-host-p99-increase-pct <BUDGET> \
  --max-es-p99-increase-pct <BUDGET> \
  --max-imu-p99-increase-pct <BUDGET> \
  --max-recovery-p95-increase-pct <BUDGET> \
  --max-rss-growth-delta-mib-per-hour <BUDGET>
```

The values must come from an explicit requirement, experiment design, or established baseline policy. This document does not invent them.

## Recommended comparison axes

The same comparator can be used for:

```text
before change      vs after change
firmware A         vs firmware B
SDK version A      vs SDK version B
Windows            vs Linux
MJPEG              vs YUYV   (use --allow-mode-change; interpret as cross-mode evidence)
short baseline     vs repeated short baseline
one-hour soak A    vs one-hour soak B
```

Cross-mode comparison is inherently not like-for-like. The comparator therefore treats mode mismatch as FAIL by default; `--allow-mode-change` downgrades it to WARN while keeping the difference explicit.

## Qualification interpretation

### Hard failure evidence

Examples:

- no valid decoded frames;
- characterizer assessment `fail`;
- fatal injected-fault operation failure;
- recovery failure or unrecovered event;
- configured numeric gate exceeded.

### Warning / investigation evidence

Examples:

- timeouts or decode errors increase versus baseline;
- sequence drops/duplicates/out-of-order increase versus baseline;
- selected/returned mode mismatch;
- SDK timestamp encoding changes;
- provenance changes that explain a behavior shift;
- large performance/RSS deltas without a configured acceptance budget.

### What remains a measured fact, not a verdict

- exact RSS slope before a project-specific limit exists;
- camera↔IMU temporal accuracy;
- physical A/B → left/right mapping;
- hardware-sync error;
- optical calibration quality.

Those require their respective #35, #8, and #47 evidence paths.

## Completion rule for #35 physical qualification

The host-acquisition slice should not be considered physically qualified until the delivered device has produced evidence for:

```text
Q0 provenance
Q1 60 s baseline
Q2 10 min sustained run
Q3 1 h soak
Q4 stop/start recovery
Q5 SDK reconnect recovery
Q6 physical unplug/replug outcome
camera A/B physical mapping
timing + IMU continuity
actual target-mode behavior
```

Q7 is recommended where the lab setup permits it but is not automatically required for the first reference-device closure.

Related: #35, #8, #10, #47.
