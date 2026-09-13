# Bividi Architecture

Status: **foundation contract — Issue #2**

Bividi turns synchronized stereo views of the physical world into calibrated, measurable observations. It deliberately stops before assigning higher-level semantic meaning.

## 1. Core rule

```text
observation != meaning
```

Bividi may produce images, geometry, disparity, depth, validity, and quality metadata. Those outputs are evidence about a scene; they are not semantic truth, object identity, or decision authority.

## 2. System boundary

```text
physical world
      |
      v
stereo source
      |
      v
transport / acquisition
      |
      v
stereo-pair extraction
      |
      v
calibration context
      |
      v
rectification
      |
      v
disparity / depth
      |
      v
quality / validity
      |
      v
stable stereo observation
      |
      +--> visualization / debug
      +--> robotics / SLAM
      +--> CV / ML
      +--> future grounding experiments
```

The dependency direction is downward only. A consumer must not be required to know the sensor model, transport packing, or capture backend in order to consume a stereo observation.

## 3. Architectural roles

### Stereo source

The physical or replayed origin of a stereo stream. The first reference source is the Waveshare AR0144 Stereo USB Camera (A), but AR0144 is not part of Bividi's architectural identity.

A future source may use another sensor, another transport, or recorded data.

### Transport / acquisition

Responsible for acquiring host-visible frames and acquisition metadata from a source.

Examples may include UVC/V4L2, DirectShow, FFmpeg, or another backend. These are implementation mechanisms, not public architecture.

### Stereo-pair extraction

Converts transport-specific payloads into an explicit left/right pair.

```text
transport payload != stereo pair
```

Side-by-side packing, multiple video nodes, interleaving, padding, and left/right ordering belong below this boundary.

### Calibration context

Binds a stereo pair to the calibration needed to interpret its geometry. Calibration identity must remain distinguishable from nominal vendor specifications.

### Rectification

Produces a geometrically aligned pair from a calibrated pair. A rectified pair is a derived observation and must remain distinguishable from the originally captured pair.

### Disparity / depth

Produces optional geometric derivatives. Invalid, occluded, missing, or low-confidence regions remain explicit; they are not converted into invented depth.

### Quality / validity

Carries measurable status such as acquisition validity, synchronization quality, rectification error, disparity validity, latency, and drop/jitter information where available.

### Stereo observation

The durable consumer boundary. Its exact schema is intentionally deferred until characterization work establishes what must be preserved. Issue #11 owns that freeze.

## 4. Required separations

```text
vendor claim != descriptor evidence != measured behavior

transport acquisition
!= stereo-pair extraction
!= calibration / rectification
!= disparity / depth
!= observation packaging

raw captured evidence != derived geometry

missing != failed != invalid != negative observation

confidence / quality != semantic authority
```

These separations are design constraints, not naming preferences.

## 5. Evidence hierarchy

When documentation and hardware disagree, preserve the disagreement.

For host-visible behavior, prefer:

```text
measured captured behavior
    > device/UVC descriptor evidence
    > current product specification
    > generic/manual/marketing text
```

This hierarchy does not make one source infallible; it defines which evidence controls an implementation claim.

## 6. Device-specific versus core behavior

Device-specific details belong behind a device/profile boundary, including:

- VID/PID and product strings;
- UVC mode quirks;
- frame packing;
- left/right ordering;
- mode-specific crop/scale behavior;
- control quirks;
- known synchronization constraints.

Core processing must not require `AR0144`, `Waveshare`, `USB`, `UVC`, `OpenCV`, or any one matcher algorithm to appear in its public observation model.

## 7. Status model

The final runtime representation is not frozen yet, but Bividi must preserve distinctions equivalent to:

- valid acquisition;
- missing acquisition;
- acquisition failure;
- malformed or unsupported payload;
- invalid stereo pairing / desynchronization;
- valid pair with invalid derived geometry.

A downstream stage may add failure/quality information, but must not silently rewrite an upstream failure into a valid observation.

## 8. Repository layout

The initial repository layout is intentionally language-neutral:

```text
README.md
assets/

docs/
  architecture.md
  devices/
  characterization/

src/
tools/
tests/
config/
  devices/
calibration/
data/
```

Roles:

- `docs/` — durable architecture, device facts, protocols, and measured characterization summaries;
- `src/` — executable library/runtime code once the implementation language is chosen;
- `tools/` — probes, capture/calibration utilities, and inspection tools;
- `tests/` — hardware-independent tests plus explicit hardware integration tests later;
- `config/devices/` — device/mode profiles and quirks after they are measured;
- `calibration/` — small calibration metadata/artifact manifests, not large image collections;
- `data/` — artifact conventions/manifests; large raw media are excluded from ordinary Git history.

## 9. Artifact policy

Normal Git history should contain small, reviewable artifacts:

- Markdown documentation;
- text/JSON/YAML descriptors and manifests;
- compact calibration parameter files;
- tiny synthetic fixtures when justified;
- hashes and metadata for externally stored captures.

Large raw image/video/calibration datasets should stay outside ordinary Git history unless the project explicitly adopts an artifact/LFS strategy.

## 10. Non-goals

Bividi does not own:

- semantic truth or semantic admission;
- object ontology or general scene understanding;
- decision/policy authority;
- LSMM runtime behavior;
- application-specific robotics policy;
- universal benchmarking of every stereo algorithm.

A future LSMM experiment may consume Bividi observations, but LSMM does not define Bividi's core schema.

## 11. First reference device

The first pair of eyes is the Waveshare AR0144 Stereo USB Camera (A). Product facts, assumptions, and unknowns are owned by Issue #3. Actual USB/UVC behavior is owned by Issue #4.

No unverified claim about frame packing, device topology, bridge IC, or stable frame rate is part of this architecture contract.
