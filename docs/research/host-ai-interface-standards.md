# Host, Robotics, Recording, and AI Interface Standards

Status: research conclusion for Issue #27

Bividi should not invent one monolithic protocol for camera control, high-rate stereo data, recording, robotics, and AI-agent interaction. These are different planes with different latency, bandwidth, and interoperability requirements.

## 1. Recommended architecture

```text
                              +----------------------+
                              |   AI / LLM / Agent   |
                              +----------+-----------+
                                         |
                              MCP tools / resources
                                         |
                              +----------v-----------+
                              |  Bividi host service |
                              |  control + metadata  |
                              +----------+-----------+
                                         |
                    +--------------------+--------------------+
                    |                    |                    |
                    v                    v                    v
             in-process API        ROS 2 adapter        recorder/replay
                    |                    |                    |
          frame / observation      Image/CameraInfo          MCAP
                    |              Disparity/Cloud             |
                    +--------------------+--------------------+
                                         |
                              +----------v-----------+
                              |    Bividi core       |
                              | observation model    |
                              +----------+-----------+
                                         |
                              capture / source adapter
                                         |
                              +----------v-----------+
                              | USB UVC / future     |
                              | stereo sources       |
                              +----------------------+
```

The Bividi core remains independent of ROS 2, MCP, MCAP, GStreamer, and any one capture backend. Adapters map the same Bividi observation into established ecosystems.

## 2. Plane separation

### 2.1 Device / camera plane — UVC first

The Waveshare reference camera is a USB Video Class device, so UVC plus the host OS camera API is the authoritative device-facing plane for the first source.

Examples:

- Linux: V4L2/UVC
- Windows: Media Foundation / DirectShow-class host APIs
- optional media backend: FFmpeg/GStreamer/OpenCV

Bividi must not expose backend-specific packing above the source adapter.

### 2.2 Camera capability vocabulary — GenICam is useful, but not the device contract

GenICam defines a generic programming model for cameras and includes:

- GenApi — self-describing camera API via XML
- SFNC — standard feature names and semantics
- PFNC — standard pixel-format names
- GenTL — transport-layer API

This is a strong reference vocabulary for future industrial-camera adapters and for naming camera capabilities consistently.

However, the Waveshare AR0144 USB camera is currently known as a UVC device, not a USB3 Vision / GenICam-compliant camera. Bividi must not pretend that it exposes a GenICam node map.

Recommended use:

```text
GenICam/SFNC
    -> vocabulary/inspiration for generic capability names
    -> future adapter target for compliant cameras
    != Waveshare control protocol
```

Reference:
- https://www.emva.org/standards-technology/genicam/introduction-new/
- https://www.emva.org/standards-technology/genicam/

## 3. Robotics interoperability — ROS 2 is the strongest existing mapping

ROS 2 already defines durable message contracts for most of Bividi's geometric outputs.

### 3.1 Raw/decoded image

`sensor_msgs/Image`

Important semantic match:

- message timestamp should represent image acquisition time;
- `frame_id` identifies the optical frame;
- width/height/encoding/step/data are explicit.

Reference:
- https://docs.ros.org/en/ros2_packages/jazzy/api/sensor_msgs/msg/Image.html

### 3.2 Calibration and rectification metadata

`sensor_msgs/CameraInfo`

This already carries:

```text
image width / height
D  distortion coefficients
K  intrinsic matrix
R  rectification matrix
P  projection matrix
ROI / binning
```

For horizontal stereo, the right-camera projection matrix can encode the baseline through `Tx = -fx' * B`.

This maps very naturally to Bividi calibration artifacts.

Reference:
- https://docs.ros.org/en/rolling/p/sensor_msgs/msg/CameraInfo.html

### 3.3 Disparity

`stereo_msgs/DisparityImage`

The ROS message includes:

```text
disparity image
f   focal length in pixels
t   baseline
valid window
min/max disparity
disparity increment
```

It explicitly documents the stereo relation:

```text
Z = f * t / d
```

Reference:
- https://docs.ros.org/en/kilted/p/stereo_msgs/msg/DisparityImage.html

### 3.4 Point cloud

Use `sensor_msgs/PointCloud2` when Bividi materializes XYZ or XYZ+attributes.

Reference:
- https://docs.ros.org/en/ros2_packages/iron/api/sensor_msgs/index.html

### 3.5 Image transport

ROS `image_transport` provides transparent raw/compressed image transport and pairs camera images with `CameraInfo`.

Reference:
- https://docs.ros.org/en/iron/p/image_transport/

### 3.6 ROS 2 is an adapter, not the core

Bividi should map cleanly to ROS 2 but must not require a ROS installation for basic capture, calibration, testing, or AI-agent use.

Recommended topic shape later:

```text
/bividi/left/image_raw
/bividi/left/camera_info
/bividi/right/image_raw
/bividi/right/camera_info
/bividi/disparity
/bividi/depth              optional project-specific mapping
/bividi/points             optional PointCloud2
/bividi/status             Bividi-specific quality/status metadata
```

The final names remain implementation details until the ROS adapter issue is opened.

## 4. Real-time distributed transport — DDS via ROS 2

DDS is an OMG standard for real-time publish/subscribe systems with configurable QoS such as reliability, deadlines, bandwidth, and resource limits.

Bividi does not need to implement DDS directly. ROS 2 already provides a practical robotics-facing abstraction over DDS-compatible middleware.

Reference:
- https://www.omg.org/omg-dds-portal/index.htm

## 5. High-rate media plane — in-process memory first; GStreamer when a media pipeline is useful

For local CV/ML inference, the lowest-friction path is an in-process image/tensor reference rather than serializing every frame through JSON, MCP, or a network protocol.

For media pipelines, GStreamer is a strong adapter option because its buffers carry media data and timestamps and it supports live streaming/decoding pipelines.

Recommended role:

```text
UVC / decoder
   -> GStreamer adapter (optional)
   -> Bividi source adapter
   -> StereoPair / StereoObservation
```

GStreamer is not the semantic observation schema; it is a media/data-plane mechanism.

References:
- https://gstreamer.freedesktop.org/documentation/application-development/basics/data.html
- https://gstreamer.freedesktop.org/documentation/additional/design/streams.html

## 6. Recording and replay — MCAP

MCAP is a schema-aware container designed for timestamped message streams and is already integrated with ROS 2 through rosbag2.

This fits Bividi better than inventing a directory of loosely related image files for every experiment.

Recommended role:

```text
Bividi observation stream
        |
        +--> MCAP with ROS-compatible schemas
        |
        +--> MCAP with Bividi-native metadata schema when needed
```

Use MCAP for durable experiment recording, replay, synchronized metadata, and later comparison of algorithms.

Large raw captures may still remain outside normal Git history; Git should retain manifests, hashes, summaries, and small fixtures.

References:
- https://mcap.dev/spec
- https://mcap.dev/guides/getting-started/ros-2

## 7. AI / LLM control plane — MCP

Model Context Protocol is the strongest current standard candidate for connecting Bividi to LLM/agent hosts.

MCP provides three relevant primitives:

```text
Tools      -> model-invoked operations
Resources  -> data/context exposed by URI
Prompts    -> user-selected workflows
```

The 2026-07-28 MCP specification uses a stateless protocol core, and official SDKs exist for Python, TypeScript, C#, Go and others.

References:
- https://blog.modelcontextprotocol.io/posts/2026-07-28/
- https://modelcontextprotocol.io/specification/
- https://github.com/modelcontextprotocol/python-sdk

### 7.1 Good MCP operations for Bividi

Read-only / inspection examples:

```text
bividi.list_sources
bividi.get_source_status
bividi.list_modes
bividi.list_controls
bividi.get_calibration
bividi.get_quality_summary
bividi.get_latest_observation_metadata
```

Controlled actions later:

```text
bividi.capture_snapshot
bividi.start_recording
bividi.stop_recording
bividi.run_calibration_capture
bividi.run_characterization
bividi.set_control
```

Potentially destructive or persistent device operations must remain separately permissioned and must not be added merely because an undocumented vendor command is discovered.

### 7.2 MCP resources

Useful resources can expose stable URIs such as:

```text
bividi://source/default/status
bividi://source/default/calibration/current
bividi://observation/latest/metadata
bividi://observation/<id>/left
bividi://observation/<id>/right
bividi://observation/<id>/disparity
bividi://recording/<id>/manifest
```

MCP resources can carry text or binary content, but that does **not** make MCP an appropriate continuous 30/60 FPS video transport.

Recommended rule:

```text
MCP = discovery + control + metadata + selected snapshots/resources
MCP != continuous stereo media pipe
```

For an AI system that needs continuous perception, use the native/in-process, ROS 2, or media data plane and let MCP control/query that subsystem.

## 8. CV/ML model interface

There is no single universal stereo-camera-to-AI wire standard comparable to UVC for cameras or MCP for LLM tools.

For conventional CV/ML inference, Bividi should expose an in-process observation API that allows adapters to produce:

```text
left image
a right image
rectified pair
disparity/depth
validity mask
calibration
timestamps/source identity
```

A model-specific adapter can then convert those objects into NumPy, PyTorch, ONNX Runtime, TensorRT, OpenVINO, etc. Tensor/model runtimes are execution APIs, not the Bividi observation protocol.

## 9. Bividi-native contract still required

Standards cover many pieces, but none captures every Bividi requirement at once.

Bividi still needs a small internal observation model containing at least these concepts:

```text
source identity
observation identity / sequence
acquisition timestamp(s)
left/right payload references
capture mode / encoding
acquisition status
synchronization status / quality
calibration identity
processing stage / producer version
optional disparity/depth references
validity / quality metadata
```

This is an **internal semantic contract**, not a new network protocol.

Adapters should map this contract into ROS 2, MCAP, MCP resources, Python objects, or other external forms.

## 10. Recommended implementation order

```text
1. Bividi host-domain types + provider interface
2. hardware-independent mock/synthetic provider
3. CLI for status/schema/probe operations
4. MCP read-only adapter using the official MCP Python SDK
5. real UVC provider after #4/#5 measurements
6. MCAP recorder/replay adapter
7. ROS 2 adapter
8. optional GStreamer/high-performance media adapters
```

This order allows host and AI integration to be developed and tested before the physical camera arrives without encoding unverified AR0144 behavior.

## 11. Language recommendation

Use Python for the **reference host implementation and AI adapter** initially because:

- official MCP Python SDK v2 supports the current 2026-07-28 specification;
- CV/calibration tooling has strong Python/OpenCV/NumPy support;
- ROS 2 and MCAP ecosystems have Python integration;
- host research utilities are easier to iterate;
- Bividi architecture remains language-neutral, so performance-critical processing can move to C/C++/Rust later without changing the observation contract.

Python is an implementation choice for the first host stack, not an architectural requirement.

## 12. Decision

Adopt a layered interoperability model:

```text
Device:        UVC / OS camera API
Vocabulary:    GenICam/SFNC concepts where useful, no fake compliance
Core:          Bividi-native observation model, in-process first
Robotics:      ROS 2 message adapters
Realtime bus:  DDS indirectly through ROS 2
Recording:     MCAP
Media pipe:    GStreamer optional
AI/LLM:        MCP control/resource adapter
CV/ML:         in-process tensor/image adapters
```

Do not design a new Bividi wire protocol at this stage.
