# Bividi Documentation Map

The current concrete reference-device line is **stereo AR0234 + IMU**. Core architecture remains platform/device independent.

## Architecture

- [`architecture.md`](architecture.md) — durable system boundary and dependency direction
- [`host.md`](host.md) — hardware-independent host API and backend/adapter boundary
- [`native-runtime.md`](native-runtime.md) — C++/OpenCV production runtime and Python reference/oracle role
- [`recording.md`](recording.md) — recording/replay contract and MCAP role

## Active reference device

- [`devices/decxin-ar0234.md`](devices/decxin-ar0234.md) — DECXIN AR0234 stereo + IMU module facts, purchased 100° configuration, interfaces, and current unknowns
- [`devices/decxin-nori-sdk-surface.md`](devices/decxin-nori-sdk-surface.md) — Nori_Xvision Windows/Linux SDK surface and backend constraints
- [`protocols/decxin-nori-timestamp-imu.md`](protocols/decxin-nori-timestamp-imu.md) — DECXIN/Nori timestamp and ICM42688 IMU transport format

## Characterization

- [`characterization/usb-uvc-test-plan.md`](characterization/usb-uvc-test-plan.md) — live host/interface characterization for the AR0234 reference device
- [`characterization/stereo-transport-test-plan.md`](characterization/stereo-transport-test-plan.md) — live camera A/B mapping and transport verification

## Research / interoperability

- [`research/host-ai-interface-standards.md`](research/host-ai-interface-standards.md) — host/robotics/recording/AI standards audit
- [`research/bividi-llmc-lsmm-integration.md`](research/bividi-llmc-lsmm-integration.md) — Bividi → llm.c → lsmm.c boundary and provenance model
- [`research/transport-note.md`](research/transport-note.md) — short transport-independence note

## AI

- [`ai-mcp.md`](ai-mcp.md) — MCP adapter role and run notes

Historical camera-candidate research is intentionally kept in Git history / Issues rather than the current documentation tree.
