# Bividi Documentation Map

## Architecture

- [`architecture.md`](architecture.md) — durable system boundary and dependency direction
- [`host.md`](host.md) — hardware-independent host API and CLI
- [`recording.md`](recording.md) — recording/replay contract and MCAP role

## Devices

- [`devices/decxin-ar0234.md`](devices/decxin-ar0234.md) — DECXIN AR0234 stereo + IMU module facts, purchased 100° configuration, interfaces, and current unknowns
- [`devices/decxin-nori-sdk-surface.md`](devices/decxin-nori-sdk-surface.md) — Nori_Xvision Windows/Linux SDK surface and backend constraints
- [`devices/`](devices/) — durable source-backed facts for concrete devices

## Protocols

- [`protocols/decxin-nori-timestamp-imu.md`](protocols/decxin-nori-timestamp-imu.md) — DECXIN/Nori encoded timestamp and ICM42688 IMU transport format

## Research

- [`research/ar0144-external-evidence.md`](research/ar0144-external-evidence.md) — external AR0144/Waveshare implementation evidence
- [`research/ar0144-control-firmware-surface.md`](research/ar0144-control-firmware-surface.md) — USB control and firmware-access audit
- [`research/host-ai-interface-standards.md`](research/host-ai-interface-standards.md) — host/robotics/recording/AI standards audit
- [`research/bividi-llmc-lsmm-integration.md`](research/bividi-llmc-lsmm-integration.md) — Bividi → llm.c → lsmm.c boundary and provenance model

## Characterization

- [`characterization/usb-uvc-test-plan.md`](characterization/usb-uvc-test-plan.md) — USB/UVC measurement protocol
- [`characterization/stereo-transport-test-plan.md`](characterization/stereo-transport-test-plan.md) — stereo packing/orientation measurement protocol

## AI

- [`ai-mcp.md`](ai-mcp.md) — MCP adapter role and run notes
