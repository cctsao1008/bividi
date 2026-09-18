# SensorObservation MCAP v1

Status: first generic Bividi `SensorObservation` MCAP storage codec.

This adapter is intentionally outside Bividi Core. MCAP is a storage/interoperability container; the durable domain model remains the native `SensorCapabilities` / `SensorObservation` contract.

## Boundary

```text
SensorObservation v1
        ↓
Python MCAP adapter
        ↓
Bividi MCAP profile v1
        ↓
Python MCAP adapter
        ↓
SensorObservation v1
```

The optional Python dependency is installed with:

```bash
python -m pip install -e ".[mcap]"
```

Normal C++ capture/replay does not depend on MCAP or ROS.

## Profile

MCAP header profile:

```text
bividi.sensor_observation.mcap.v1
```

Observation envelope schema:

```text
bividi.mcap.sensor_observation.v1
```

The envelope mirrors the frozen #11 observation fields:

- contract version;
- source identity and evidence kind;
- source/observation validity;
- sequence and sequence-presence;
- continuity epoch/state;
- host/replay timing points;
- calibration identities;
- configuration revision;
- camera metadata, frame/exposure timing, and validity;
- raw/SI IMU fields and validity;
- stereo-pair synchronization state.

The MCAP-specific envelope adds only `mcap_ordinal` plus camera-payload references/hashes. These fields are removed again on readback.

## Channels

Normalized observation metadata is carried on:

```text
/bividi/observation
```

Camera payloads use source- and stream-qualified channels:

```text
/bividi/source/<percent-encoded-source-id>/camera/<percent-encoded-stream-id>
```

Camera bytes use message encoding:

```text
application/x-bividi-packed-image-v1
```

The v1 payload contract is deliberately narrow:

- `GRAY8` or `BGR24` only;
- tightly packed rows only (`row_stride == width * bytes_per_pixel`);
- exact byte length required;
- SHA-256 and byte count stored in the observation envelope;
- missing, duplicate, unreferenced, size-mismatched, or hash-mismatched payloads are rejected.

Non-tight borrowed image views are not silently repacked in v1 because that could change representation semantics or copy unrelated stride padding. A later adapter revision may define an explicit row-packing transform with provenance if needed.

## MCAP sequence and ordering

MCAP `message.sequence` is the zero-based container observation ordinal. The original Bividi `sequence` remains in the observation envelope and is never replaced by the MCAP sequence field.

Camera payload messages and their observation envelope share the same MCAP ordinal so the reader can bind them without using producer timestamps as join keys.

## Timestamp policy

The adapter intentionally does **not** map any Bividi producer clock into MCAP `log_time` or `publish_time`.

For v1, both MCAP time fields use a deterministic container-order clock:

```text
container_time_ns = mcap_ordinal * 1_000_000
```

That clock exists only so the MCAP file has deterministic ordering. It is not host receive time, exposure time, IMU time, replay scheduling time, UTC, or a physical synchronization claim.

All producer timing evidence remains in the observation envelope with its original:

- ticks;
- unit;
- clock domain;
- clock ID;
- finite-width raw timestamp evidence where present.

This preserves the existing Bividi rule:

```text
container/storage time != producer/device time != replay scheduling time
```

## Semantic round-trip

`semantic_digest()` canonicalizes the supported observation contract and hashes all semantic fields. Camera bytes contribute by SHA-256 + payload length, so a one-byte pixel change changes the digest.

The CI fixture covers:

```text
stereo GRAY8 + raw IMU
IMU-only observation
BGR24 camera + invalid raw IMU sample
        ↓
write MCAP
        ↓
read MCAP
        ↓
compare semantic digests + exact camera bytes/timestamps
```

The test explicitly preserves `unknown` stereo synchronization. Storage round-trip must never upgrade unknown synchronization into a measured claim.

## Integrity / rejection behavior

The v1 reader/writer rejects, rather than repairs:

- unsupported observation contract versions;
- unknown/extra fields at the adapter boundary;
- malformed timestamp structures;
- invalid enum values;
- non-tight camera stride;
- pixel-format/bytes-per-pixel mismatch;
- image byte-size mismatch;
- duplicate camera stream IDs within one observation;
- unsupported MCAP profile/schema identity;
- duplicate observation ordinals;
- non-contiguous observation ordinals;
- missing/duplicate/unreferenced camera payloads;
- camera payload size or SHA-256 mismatch.

## Relationship to ROS2 MCAP

This file format is Bividi-native MCAP storage. It is separate from the existing ROS2 calibration transport adapter, which writes standard ROS2 `sensor_msgs` into rosbag2/MCAP for robotics-tool interoperability.

```text
Bividi SensorObservation MCAP
    = native storage / semantic round-trip

ROS2 rosbag2 + MCAP
    = external robotics interoperability

ROS1 .bag
    = narrow legacy compatibility boundary for the pinned upstream Kalibr solver
```

None of those transport formats replace the Bividi observation contract.

## Current limitations / next slice

The first codec establishes the versioned storage contract and exact hardware-independent semantic round-trip. Follow-up work in #31 should connect live/native C++ recording output to this adapter and add direct MCAP replay/source integration, while keeping the MCAP dependency optional.

MCAP round-trip success is software/storage evidence only. It does not validate AR0234 physical synchronization, camera mapping, calibration accuracy, USB recovery, or IMU scale.
