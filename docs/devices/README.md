# Device notes

This directory contains durable, source-backed facts for concrete sensor devices and vendor host surfaces.

Current device notes:

- [`decxin-ar0234.md`](decxin-ar0234.md) — DECXIN AR0234 stereo + IMU module facts and current unknowns
- [`decxin-nori-sdk-surface.md`](decxin-nori-sdk-surface.md) — Nori_Xvision SDK/API surface relevant to Bividi

Device documents must distinguish:

- vendor specification or declaration;
- SDK/API evidence;
- sample/decoder evidence;
- inference;
- unknowns;
- measured behavior.

Device-specific facts must not silently become core Bividi contracts. When live measurements disagree with vendor material, preserve the discrepancy and let measured behavior control the implementation claim.
