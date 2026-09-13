# Bividi → llm.c → lsmm.c integration note

Status: architectural research note

## Short answer

A Bividi → llm.c → lsmm.c chain is possible, but USB is not the natural boundary between Bividi and llm.c when they run on the same host.

The physical USB boundary is normally:

```text
AR0144 stereo camera
    ↓ USB/UVC
Bividi host
```

From Bividi onward, use an in-process API, local IPC, MCAP/replay artifact, ROS 2/DDS adapter, or another host-side transport as appropriate.

## Current constraint: llm.c is language-model machinery

The current `cctsao1008/llm.c` codebase is derived from the simple C/CUDA GPT-2/GPT-3 training/inference project. Its native input domain is token sequences; it does not currently define a vision encoder or a Bividi observation input contract.

Therefore this is not valid without an adapter:

```text
StereoObservation → llm.c
```

A proposal adapter must first transform selected Bividi evidence into an input representation llm.c can consume, for example:

- textualized measurements or structured summaries encoded as tokens;
- symbolic observations produced by deterministic CV;
- later, a learned vision/embedding front end if llm.c is deliberately extended toward multimodal inference.

Such a transformation is derived interpretation, not the original grounding evidence.

## LSMM-compatible boundary

LSMM already treats grounding as external and allows language, vision, sensor, symbolic tools, or human operators to act as proposal machinery.

The preferred conceptual architecture is therefore:

```text
physical world
    ↓
AR0144 stereo camera
    ↓ USB/UVC
Bividi
    ↓
StereoObservation + calibration + validity + provenance
    ├───────────────────────────────┐
    │                               │
    │ direct grounding path         │ proposal path
    ↓                               ↓
LSMM Grounding G              perception adapter
                                    ↓
                                  llm.c
                                    ↓
                           typed proposal + refs
                                    ↓
                                  lsmm.c
```

This preserves two distinct facts:

1. Bividi observations are evidence from the world.
2. llm.c output is an interpretation/proposal about that evidence.

llm.c must not become the sole provenance path from the camera to LSMM.

## Why a direct Bividi → LSMM grounding path matters

If the only chain were:

```text
Bividi → llm.c → lsmm.c
```

then LSMM would receive only the language model's derived interpretation unless the original observation references were preserved. That would collapse observation and interpretation.

Instead every proposal should be able to cite the Bividi observation that motivated it:

```text
proposal
  producer: llm.c / model-id / version
  grounding_refs:
    - bividi://observation/<id>
  derived_from:
    - image/depth/quality artifact hashes
  confidence/status: producer-defined
```

LSMM remains responsible for semantic formation, judgment, consequence, and authorization.

## Transport recommendation

Do not define `USB` as the generic Bividi→AI protocol.

Recommended layers:

```text
camera → Bividi:       USB/UVC
Bividi internal:       typed in-process host API
record/replay:         MCAP
robotics integration:  ROS 2 / DDS adapter
AI-agent control:      MCP
llm.c integration:     local adapter/API/IPC chosen by deployment
LSMM grounding:        typed observation/provenance references
```

If llm.c and lsmm.c later run on a separate embedded processor, USB could be one physical transport, but the logical observation/proposal schema should remain transport-independent.

## First integration experiment

Before adding real vision inference, use a deterministic synthetic path:

```text
MockStereoProvider
    ↓
Bividi StereoObservation
    ↓
small deterministic observation-to-text adapter
    ↓
llm.c prompt/inference
    ↓
typed proposal referencing observation_id
    ↓
lsmm.c grounding/proposal admission experiment
```

The experiment should prove provenance preservation and boundary semantics, not vision quality.

## Architectural invariant

```text
observation != interpretation != semantic admission

Bividi evidence
    != llm.c proposal
    != lsmm.c admitted semantic state
```

That separation should survive whether the physical transport is USB, shared memory, files, sockets, ROS 2, or another bus.
