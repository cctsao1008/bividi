# Bividi MCP Adapter

Status: initial read-only AI adapter — Issue #29

Bividi uses the Model Context Protocol (MCP) as an **AI/agent control and metadata plane**.

It is not the continuous stereo-video data plane.

## 1. Why MCP

MCP gives LLM/agent hosts a standard mechanism to discover and invoke tools and read resources without Bividi inventing a custom AI protocol.

The current reference implementation targets the official MCP Python SDK v2, which supports the 2026-07-28 MCP specification line.

## 2. Current tools

```text
bividi.about
bividi.list_sources
bividi.get_source_status
bividi.list_modes
```

All current operations are read-only and use the same `BividiHost` API as the CLI.

The adapter does not contain UVC, OpenCV, ROS, or device-specific code.

## 3. Current resources

```text
bividi://host/about
bividi://sources
```

Resources are intentionally small metadata objects.

Future image/snapshot resources may be added after an observation/capture API exists, but MCP must not become a continuous 30/60 FPS transport.

## 4. Install

Base Bividi remains dependency-free.

Install the optional MCP adapter with:

```bash
python -m pip install -e ".[mcp]"
```

The optional dependency is:

```text
mcp >= 2, < 3
```

## 5. Run

With the official MCP CLI installed through the optional dependency:

```bash
mcp dev src/bividi/mcp_server.py
```

or run the installed stdio entry point:

```bash
bividi-mcp
```

The current server uses the synthetic provider, so no camera is required.

## 6. Data-plane rule

```text
AI asks for capability/status/action
        -> MCP

AI/application needs one selected snapshot/resource
        -> MCP resource may be appropriate later

continuous stereo frames / depth stream
        -> native/in-process, ROS 2, GStreamer, or another media plane
        != MCP
```

This separation prevents a JSON/agent protocol from becoming an accidental high-rate media transport.

## 7. Safety boundary

The initial adapter exposes no persistent or destructive device operation.

If future hardware research discovers vendor-specific control commands, they must first pass the firmware/control safety gate in Issue #4/#26 before any AI-accessible write operation is considered.

## 8. Next expansion

After the underlying host APIs exist, MCP can expose controlled operations such as:

```text
capture_snapshot
get_latest_observation_metadata
get_calibration
start_recording
stop_recording
run_characterization
```

The adapter must continue to call the Bividi host API rather than talking directly to device backends.
