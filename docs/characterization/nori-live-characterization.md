# Nori Live Characterization Harness

Owner: Issue #35  
Reference device: DECXIN AR0234 stereo + ICM-42688-P  
Tool: `bividi-nori-characterize`  
Status: RSS + controlled recovery characterization implemented; physical AR0234 measurements pending

## Purpose

`bividi-nori-characterize` is the repeatable measurement harness for the live Nori capture path. It runs the same transport-normalization and DECXIN decode path used by the live session, but records evidence rather than rendering UI previews.

```text
Nori SDK pull buffer
        ↓
RawFrame
        ↓
owned MJPEG / YUYV / BGR24 normalization
        ↓
DECXIN decoder
        ↓
per-frame trace
RSS samples
controlled stop/start + software reconnect trials
        ↓
statistical / recovery summary
```

The tool is deliberately evidence-oriented. It does not rename camera A/B to left/right, infer synchronization quality from host arrival time, or subtract timestamps from unrelated clock epochs.

## Build

The executable is built only when both the supplied Nori SDK and the OpenCV-backed transport-normalization path are available:

```bash
cmake -S . -B build-nori \
  -DBIVIDI_WITH_NORI_SDK=ON \
  -DBIVIDI_NORI_SDK_ROOT=/path/to/Nori-sdk
cmake --build build-nori --config Release
```

Normal CI does not require vendor binaries. The characterizer translation unit is nevertheless compile-checked in hardware-independent CI, and the shared characterization primitives are unit-tested on Linux and Windows.

## Recommended bring-up sequence

First enumerate the delivered device and mode indexes:

```bash
bividi-nori-probe
```

Then perform a short smoke run before introducing recovery faults:

```bash
bividi-nori-characterize \
  --device 0 \
  --mode 0 \
  --duration-s 60 \
  --warmup-frames 30 \
  --rss-sample-ms 1000 \
  --output-prefix ar0234_smoke
```

`device=0` and `mode=0` are examples only. Use the actual indexes reported by `bividi-nori-probe`.

Useful staged runs are:

```text
60 s   → basic decode / continuity / RSS sanity
10 min → sustained FPS / jitter / intermittent anomalies
1 h    → long-run continuity + RSS trend
fault run → controlled stop/start and stream reopen/recovery
```

Example controlled recovery run:

```bash
bividi-nori-characterize \
  --device 0 \
  --mode 0 \
  --duration-s 600 \
  --rss-sample-ms 1000 \
  --stop-start-every-frames 3600 \
  --stop-start-pause-ms 250 \
  --reconnect-every-frames 7200 \
  --reconnect-pause-ms 500 \
  --recovery-timeout-ms 10000 \
  --output-prefix ar0234_recovery_10m
```

The frame intervals above are examples, not assumptions about the actual delivered FPS.

## Fault model

Two controlled fault/recovery operations are available.

### Stop/start

```text
Nori VideoStop
wait configured pause
Nori VideoStart
wait for first valid decoded frame
```

This measures stream restart behavior without destroying the backend object.

### Software reconnect

```text
destroy nori::Stream
wait configured pause
construct nori::Stream with the same requested device/mode
verify read-back mode
wait for first valid decoded frame
```

This is a **software close/reopen trial**. It does not claim to emulate a physical USB unplug, hub reset, cable fault, bus reset, or device power cycle. Those remain separate physical fault-injection tests.

For each injected event the tool records the operation result, first-valid-frame recovery latency, pre/post sequence values, and pre/post raw exposure-start counters. A sequence/counter decrease is useful reset evidence but must still be interpreted with finite-counter wrap semantics in mind.

## Planned gaps versus spontaneous faults

Intentional stop/reconnect downtime must not be counted as an ordinary dropped-frame burst.

The tool therefore starts a new **continuity epoch** after each injected fault:

```text
active epoch 0
    ↓ injected stop/reconnect
active epoch 1
    ↓ injected stop/reconnect
active epoch 2
```

Drop / duplicate / out-of-order statistics are accumulated **within active epochs**. The planned downtime is instead measured through the fault-event recovery record.

This keeps these two questions separate:

```text
Did normal acquisition lose continuity?
!=
How long did an intentional recovery operation take?
```

## RSS / memory characterization

Current-process resident memory is sampled with native host APIs:

```text
Windows → process working set
Linux   → /proc/self/statm resident pages
macOS   → task resident size
```

Default sampling interval:

```text
1000 ms
```

Use `--rss-sample-ms 0` to disable RSS sampling.

The summary reports:

- RSS min / max / mean / P50 / P95 / P99;
- ordinary-least-squares RSS slope in bytes/s;
- the same slope expressed as MiB/hour;
- regression R².

The RSS slope is **descriptive evidence**, not by itself a memory-leak verdict. Long runs, repeatability, allocation warm-up, SDK behavior, OS paging, and workload changes all matter.

To keep the measurement tool from creating an artificial linear RSS slope, high-rate in-memory summary inputs are bounded. Each series pre-reserves a fixed sample capacity and is deterministically decimated when full. The per-frame CSV remains the lossless evidence source.

## Error streaks and recovery deadline

The harness records both totals and longest consecutive streaks for:

```text
GetFrameBuff timeouts
decode errors
```

Injected faults have an explicit first-valid-frame recovery deadline controlled by:

```text
--recovery-timeout-ms
```

An operation exception or missed recovery deadline is recorded as a failed fault/recovery trial and causes the final assessment to fail.

## Output artifacts

Each run writes four artifacts:

```text
<PREFIX>.csv         lossless per-frame trace
<PREFIX>.rss.csv     periodic process RSS samples
<PREFIX>.events.csv  injected fault/recovery events
<PREFIX>.json        run summary + distributions + provenance
```

### Per-frame trace

The frame trace records:

- sample index and continuity epoch;
- recovery-event ID on the first frame after an injected fault;
- platform-normalized frame sequence;
- host monotonic receive timestamp and same-domain interval;
- SDK frame-time representation and same-domain interval;
- raw and extended DECXIN exposure-start/exposure-end timestamps;
- exposure-start/end frame intervals and exposure duration (`EE - ES`);
- total/valid IMU sample counts;
- first/last valid IMU timestamp and cross-frame IMU gap where available;
- raw transport byte length and returned format/geometry;
- vendor buffer index/offset provenance where exposed.

### RSS trace

The RSS CSV records:

```text
sample index
elapsed seconds
RSS bytes
RSS MiB
```

### Event trace

The event CSV records:

```text
event ID / type
frame at injection
configured pause
operation success
first-frame recovery success / latency
pre/post sequence
sequence decrease/reset evidence
pre/post raw ES counter
raw device-counter decrease/reset evidence
error text
```

### JSON summary

The JSON schema is currently:

```text
bividi.nori.characterization.v2
```

It contains device/SDK/ISP/FPGA provenance, requested/read-back mode, run counters, continuity statistics, recovery statistics, RSS trend, bounded-summary sampling provenance, timing/IMU distributions, and the individual fault-event records.

The lightweight assessment is intentionally conservative:

```text
FAIL → no decoded frames, injected operation failure, or recovery failure
WARN → timeouts/decode errors/mode mismatch or spontaneous continuity anomalies
PASS → none of the above observed
```

RSS slope is not currently used as an automatic PASS/FAIL threshold because no physical-device baseline has been established yet.

## Clock-domain rule

Three time sources may be visible during a run:

```text
host_receive_monotonic_ns
SDK Frame_Time
embedded DECXIN ES / EE / IMU time
```

They are not assumed to share an epoch.

The harness compares intervals inside each domain and preserves raw/extended values. It intentionally does not report an absolute `host - device` offset.

Camera↔IMU spatial/temporal calibration remains owned by #47, where Kalibr or another proven external solver can operate on a deliberately prepared dataset.

## Sequence semantics

The backend normalizes the vendor sequence source differently by platform:

```text
Linux   → v4l2_buffer.sequence (32-bit semantics)
Windows → Nori u_FrameNum
```

The characterizer applies explicit 32-bit wrap handling on Linux. Sequence gaps are stronger continuity evidence than comparing decoded-frame count with nominal FPS alone.

When fault injection is enabled, sequence continuity is deliberately segmented at the injected boundary; pre/post values remain in the event record so reset behavior is still visible without falsely reporting planned downtime as ordinary drops.

## What this tool still does not prove

A clean run does not by itself prove:

- physical camera A/B → left/right identity;
- optical calibration quality;
- hardware synchronization error in microseconds;
- camera↔IMU temporal offset;
- generic UVC behavior outside the Nori backend;
- physical USB unplug/replug recovery;
- hub/bus/power fault recovery;
- absence of a memory leak from one short RSS run.

Those remain explicit characterization/calibration tasks under #35, #8, #10, and #47.

## Suggested evidence retention

For each physical test session, retain the JSON summary and the three CSV traces with a stable session name identifying host/platform, device, mode, and test purpose. Large raw video captures should remain outside normal Git history; retain hashes or external references when needed.

Related: #35, #8, #10, #47.
