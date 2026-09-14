# Bividi visual identity

Bividi should feel like a **cute research instrument**: approachable at first glance, technically rigorous immediately after.

Its README and mascot now share a family resemblance with `single-wheel-platform` and `rotary-inverted-pendulum`, but Bividi keeps its own sensor-first identity.

## Hero contract

The README hero uses the same rhythm as the sibling projects:

```text
mascot
project name
research subtitle
strong one-line identity
short italic engineering principle
compact capability line
```

Current Bividi lines:

- **Stereo-Inertial Sensor Research**
- **Two eyes. One clock. Clean observations.**
- *Capture precisely. Synchronize correctly. Normalize simply.*
- `👀 Stereo · 🧭 IMU · ⏱️ Timing · 🔬 Validate`

## Mascot direction

The Bividi mascot is a small stereo-inertial sensing head.

Visual rules:

- transparent background;
- warm cream body with dark brown outlines and a soft shadow;
- two clearly separated camera/lens eyes;
- no goggle bridge or touching eye outlines;
- a small central IMU/timing cue;
- subtle stereo/synchronization accents;
- calm, friendly expression rather than exaggerated cartoon behavior;
- recognizable at README and repository-avatar scale;
- device-inspired, but not a literal drawing of one vendor camera.

The visual language intentionally matches the sibling mascots through shared cream/brown materials, soft pastel accents, rounded geometry, and restrained highlights.

## README tone

The README should be warm at the top and engineering-focused immediately afterward.

Preferred rhythm:

```text
cute hero
-> concise project identity
-> simple sensor architecture
-> current reference hardware
-> transport / timing behavior
-> host implementation path
-> validation priorities
-> repository/documentation map
```

Section headings may use one small icon. Technical paragraphs should remain plain and precise.

## Engineering emphasis

Bividi is primarily a sensor-system project. The README should emphasize:

```text
precise acquisition
efficient normalization
stable long-running capture
clear timing semantics
compact host-facing observations
```

Do not expand the project-facing language into a generic evidence ontology, semantic reasoning framework, or broad multimodal architecture unless implementation work later requires it.

Vendor-specific quirks belong below the adapter boundary. The visible Bividi contract should stay small.

## Project-facing line

> **Cute sensor. Serious timing.**

That is the intended balance: friendly presentation, strict sensor engineering.
