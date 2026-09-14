# Source code

Bividi has two deliberate implementation roles:

```text
C++17 / CMake
    production sensor runtime and hot data path

Python
    reference decoder, golden oracle, characterization, and high-level tooling
```

The native core must preserve the platform/device separation defined in `docs/architecture.md`. OpenCV may wrap native image views for processing, but OpenCV types must not become the mandatory Bividi core contract.

Device-specific transport parsing belongs below the core boundary. Runtime topology such as mono/stereo, RGB/IR, IMU, or audio presence is discovered at runtime rather than selected with build flags.

Do not place experiment history or vendor documentation in the source tree.
