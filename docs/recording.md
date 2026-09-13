# Bividi Recording and Replay Contract

Status: pre-hardware design contract

## Purpose

Define how Bividi records stereo observations for reproducible replay without making the recording container part of the core observation model.

The recommended recording container is MCAP. MCAP is an adapter/storage format; Bividi's logical observation contract remains independent of it.

## Recorded unit

A recording session should preserve enough information to reconstruct the observation context:

```text
session
  source identity
  capture mode identity
  sequence/timestamps
  left/right observation references or payloads
  acquisition/sync status
  calibration identity
  rectification state
  optional disparity/depth products
  validity/quality metadata
  producer/version metadata
  provenance/artifact hashes
```

## Required separation

```text
raw captured evidence
    !=
derived geometry
    !=
AI/semantic interpretation
```

These may coexist in one MCAP file, but must use separate logical channels/schemas so replay cannot confuse a derived result with the original capture.

## Proposed channel families

```text
/bividi/source/<id>/left
/bividi/source/<id>/right
/bividi/source/<id>/capture_status
/bividi/source/<id>/calibration
/bividi/source/<id>/disparity
/bividi/source/<id>/depth
/bividi/source/<id>/quality
/bividi/source/<id>/observation
```

Names are provisional until the final observation interface (#11) is frozen.

## Timestamp policy

Preserve producer timestamps explicitly and do not replace them with playback time.

Where available distinguish:

- device/acquisition timestamp;
- host receipt timestamp;
- processing completion timestamp;
- record/write timestamp.

Replay must retain the original timing evidence and may separately expose replay-clock time.

## Provenance

Derived outputs must identify:

- source observation ID or sequence;
- calibration ID/hash;
- processing algorithm/config version;
- producer identity;
- validity/status.

Reprocessing a recording produces a new derived result; it must not overwrite the provenance of the original result.

## Hardware-independent first step

Before the physical camera arrives, validate the contract with the synthetic provider:

```text
MockStereoProvider
  → BividiHost
  → synthetic StereoObservation
  → MCAP writer
  → MCAP reader/replay provider
  → same logical observation envelope
```

Synthetic data must remain marked synthetic throughout recording and replay.

## Non-goals

- MCAP is not the Bividi core API.
- MCAP does not define semantic truth.
- Recording success does not prove camera synchronization or timing quality.
- Large media should not be committed to normal Git history.
