# Bividi Host Reference Stack

Status: initial executable host foundation — Issue #28

The Bividi host layer is the boundary shared by command-line tools, AI adapters, robotics adapters, and future physical-camera providers.

## 1. Current structure

```text
CLI / MCP / ROS / future adapters
            |
            v
      BividiHost facade
            |
            v
 StereoSourceProvider protocol
            |
      +-----+------+
      |            |
    mock        future UVC
```

The current repository contains only a synthetic provider. This is deliberate: the real Waveshare provider must wait until Issues #4 and #5 establish measured USB/UVC topology and stereo packing.

## 2. Why the host contract exists before the camera provider

The host API can be tested without hardware and prevents future adapters from bypassing source validity and identity rules.

It also allows MCP, ROS 2, recording, and other adapters to depend on a stable logical boundary instead of directly importing OpenCV/V4L2/DirectShow code.

## 3. Evidence semantics

Every source, mode, and status carries an evidence class:

```text
synthetic  development/test fixture
declared   externally declared capability, not yet measured
measured   observed from the actual source
```

The mock provider returns only `synthetic` values. Nothing under `src/bividi/mock.py` is evidence about AR0144 hardware.

## 4. Capture-mode geometry

`CaptureMode.eye_width` and `eye_height` describe each **logical eye image** at the provider boundary.

They do not describe the transport payload. For example, a future side-by-side UVC provider may receive one wide transport frame and split it internally; that packing must not leak into the host-domain mode contract.

## 5. CLI

After installing the package in editable mode:

```bash
python -m pip install -e .
```

Examples:

```bash
bividi about
bividi sources
bividi status mock:stereo0
bividi modes mock:stereo0
bividi --json sources
```

The current output is synthetic by design.

## 6. Tests

The initial tests use only Python's standard library:

```bash
python -m unittest discover -s tests
```

No physical camera, OpenCV, ROS 2, or MCP package is required for the base host tests.

## 7. Dependency policy

The base package intentionally has no runtime dependencies.

Future dependencies belong to optional adapters:

```text
base host        standard library
MCP adapter      official MCP Python SDK
vision/UVC       chosen backend after hardware characterization
ROS 2 adapter    ROS 2 environment
MCAP adapter     MCAP package
```

## 8. Next steps

Issue #29 adds the first AI-facing adapter using MCP. Issues #4/#5 remain responsible for discovering the real Waveshare USB/UVC behavior before a physical provider is implemented.
