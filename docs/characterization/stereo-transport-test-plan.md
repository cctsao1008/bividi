# Stereo Transport Characterization Test Plan

Owner: Issue #5  
Status: pre-hardware protocol  
Last reviewed: 2026-09-14

## Objective

Determine exactly how the selected host-visible transport payload maps to physical left/right observations.

This issue begins from #4 output. It does **not** assume that a wide frame is side-by-side merely because external implementations do so.

## Questions to answer

- one payload or multiple payloads?
- horizontal side-by-side, vertical stacking, interleaving, or another layout?
- exact per-eye dimensions?
- physical left/right ordering?
- mode-dependent crop/scale/padding?
- MJPG versus YUY2 differences?
- any metadata rows/columns or duplicated borders?

## Working hypothesis from external evidence

```text
transport payload
2560x720 decoded frame
        |
        v
horizontal midpoint split
        |
   +----+----+
   |         |
1280x720 1280x720
```

This remains a hypothesis until proven on the reference camera.

## Required measurements

### 1. Preserve the untouched decoded payload

For each selected mode, record:

- decoded width/height/channels;
- pixel format at transport level;
- one or more representative frame hashes/metadata;
- whether payload dimensions remain stable across a capture run.

Do not split the frame before preserving evidence about the original geometry.

### 2. Test midpoint geometry

If the payload is wider than a plausible single-eye image:

- inspect the vertical midpoint;
- compare image content immediately left/right of the midpoint;
- look for seam, padding, duplicated columns, crop, or scaling artifacts;
- verify that both halves have internally coherent geometry.

### 3. Prove physical left/right ordering

Use a physical one-lens-at-a-time occlusion test:

```text
cover physical left lens
-> identify which payload region changes

cover physical right lens
-> identify which payload region changes
```

Repeat after reconnect/reopen to make sure ordering is stable.

Do not infer physical left/right from variable names in third-party code.

### 4. Mode-by-mode verification

Run the layout/orientation test for every transport mode Bividi intends to support.

A layout proven for MJPG `2560x720` does not automatically apply to YUY2 or another resolution.

Record per mode:

```text
transport format
transport dimensions
per-eye dimensions
packing layout
left region
right region
crop/scale notes
padding/seam notes
```

### 5. Pair integrity observations

At this stage record obvious pair anomalies:

- one half frozen while the other changes;
- duplicated half-frames;
- malformed split boundary;
- intermittent geometry change;
- one-eye corruption.

Precise temporal synchronization quality belongs to #6, but #5 must establish that the payload consistently contains a usable pair.

## Suggested physical scenes

Use simple scenes that make mapping obvious:

1. hand/finger close to only one lens;
2. lens cap or opaque card over one lens;
3. high-contrast vertical edge crossing the central field;
4. asymmetric object placed deliberately toward one camera;
5. checkerboard only after basic ordering is proven.

## Deliverable format

`docs/characterization/stereo-transport.md` should eventually contain a measured table such as:

| Mode | Payload | Packing | Physical L | Physical R | Evidence |
|---|---|---|---|---|---|
| MJPG ... | ... | ... | ... | ... | ... |

Until hardware measurement exists, this table remains empty rather than being filled from third-party assumptions.

## Parser rule

Only after a layout is measured may a device-specific parser/profile encode it.

Core code should receive an explicit pair:

```text
StereoPair
  left
  right
  mode
  acquisition metadata
  pair status
```

The core must not receive a `2560x720` side-by-side convention as part of its public contract.

## Acceptance criteria for #5 execution

- physical left/right mapping is proven with an occlusion test;
- extraction dimensions are exact and mode-specific;
- padding/crop/scale behavior is documented;
- repeated captures show stable ordering/layout;
- unsupported/ambiguous modes remain unsupported/ambiguous;
- the measured result is sufficient to implement #7 without transport assumptions leaking upward.
