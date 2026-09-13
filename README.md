<p align="center">
  <img src="assets/bividi.svg" width="190" alt="Bividi mascot — two warm hand-drawn eyes">
</p>

<h1 align="center">bividi</h1>

<p align="center"><strong>Two little eyes, one grounded view.</strong></p>
<p align="center"><em>Seeing is evidence. Meaning comes later.</em></p>

<p align="center">
  👀 See &nbsp;·&nbsp; 🧭 Sense motion &nbsp;·&nbsp; 📐 Measure geometry &nbsp;·&nbsp; 🧾 Preserve evidence
</p>

Bividi is a stereo and stereo-inertial sensing research project for turning physical sensor events into **measurable, replayable, traceable observations**.

The project starts with synchronized visual evidence, may bind inertial evidence when a rig provides it, and then derives geometry or other products without confusing those products with the original observation.

```text
observation != derived product != interpretation
```

## What Bividi is building

```text
physical world
      |
      v
   SensorRig
      |
      +--> stereo source ------> StereoObservation
      |
      +--> IMU ----------------> ImuObservation
                                  |
                    time / calibration binding
                                  |
                                  v
                       visual-inertial context
                                  |
          +-----------------------+-----------------------+
          |                       |                       |
          v                       v                       v
     rectification          disparity / depth        VIO / SLAM
          |                       |                       |
          +-----------------------+-----------------------+
                                  |
                                  v
                         ObservationProduct(s)
                                  |
                   +--------------+--------------+
                   |              |              |
                  MCAP          ROS 2        AI / tooling
```

The durable unit is not "a camera frame plus everything we know about it." Bividi keeps acquisition evidence small and explicit, then links derived results back to the observation that produced them.

## Observation model

The current architectural direction separates three roles:

- **`StereoObservation`** — immutable stereo acquisition evidence: source, sequence/time, left/right frame references, acquisition state, synchronization evidence, and provenance.
- **`ImuObservation`** — inertial samples with their own source, timestamps/clock domain, status, and provenance.
- **`ObservationProduct`** — derived results such as rectification, disparity, depth, point clouds, embeddings, or later perception outputs, each referencing its parent observation(s).

This naturally forms an **observation graph** rather than one ever-growing struct:

```text
Stereo O123 ---------+
                     +--> VI context --> pose / VIO product
IMU I700..I716 ------+

Stereo O123 --> disparity A --> depth A
           +--> disparity B --> depth B
```

The exact stable consumer contract is still being pressure-tested in [#11](https://github.com/cctsao1008/bividi/issues/11); measured hardware behavior must drive the final schema.

## Hardware direction

Bividi is deliberately **not tied to one camera module**. Hardware candidates are tracked with evidence levels so vendor claims, component facts, inference, and measured behavior remain distinct.

The current leading candidate is the **DECXIN AR0234 stereo + ICM-42688-P IMU** module: dual global-shutter sensors, USB 3, FPGA-based acquisition, external trigger/strobe/frame-sync pins, and vendor timing claims that are attractive for stereo-inertial work. Those timing numbers remain claims until independently measured.

- Detailed DECXIN evaluation: [#32](https://github.com/cctsao1008/bividi/issues/32)
- Camera/module evidence register: [#33](https://github.com/cctsao1008/bividi/issues/33)

The earlier Waveshare AR0144 USB module remains useful historical UVC/stereo research, but it is no longer the hardware mainline.

## Host and interoperability

Bividi avoids inventing one monolithic protocol for every layer.

```text
Device          UVC / OS camera APIs / device SDKs
Core            Bividi host + observation model
Recording       MCAP
Robotics        ROS 2 message adapters
Realtime bus    DDS through ROS 2 where appropriate
Media pipeline  GStreamer when useful
AI / agents     MCP for control, discovery, metadata, and selected resources
CV / ML         in-process image / tensor adapters
```

MCP is intentionally **not** the continuous stereo-video transport. High-rate media belongs on a data plane suited to it.

The hardware-independent host foundation and mock provider allow interface work to continue before a physical reference rig is finalized.

## Research discipline

Bividi distinguishes evidence levels instead of silently promoting assumptions:

```text
MEASURED
> descriptor / protocol evidence
> manufacturer documentation
> external implementations
> secondary promotional material
> inference
```

A sensor's capability does not automatically imply that a finished camera module exposes that capability to the host.

Likewise:

```text
valid observation
!=
valid derived geometry
!=
semantic truth
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — system boundary and dependency direction
- [`docs/host.md`](docs/host.md) — hardware-independent host layer
- [`docs/research/host-ai-interface-standards.md`](docs/research/host-ai-interface-standards.md) — interoperability choices
- [`docs/visual-identity.md`](docs/visual-identity.md) — mascot and README tone contract
- [`docs/devices/`](docs/devices/) — device facts and candidate notes
- [`docs/characterization/`](docs/characterization/) — measurement protocols and results

## Project rule

> **README explains the system. Issues explain the journey. Code proves the current state.**

Bividi is intentionally friendly at the door and strict about evidence once you step inside.