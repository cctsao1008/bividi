# Kimera-VIO external package/link gate

This document covers Bividi issue #142 only: the opt-in external package/link boundary for the Kimera-VIO spike.

The exact upstream revision is frozen by #137/#139:

```text
MIT-SPARK/Kimera-VIO@ce8c59b7b273ab5ac29db7e5572e1623760e19c7
```

This gate does not adopt Kimera-VIO as a product backend and does not establish VIO accuracy.

## Why the target resolver handles two names

At the pinned revision, upstream CMake defines a build-tree alias:

```text
kimera_vio::kimera_vio
```

but installs/exports the library without a namespace. Its installed `kimera_vioConfig.cmake` loads target:

```text
kimera_vio
```

Bividi therefore accepts exactly these two target surfaces and rejects any other package shape.

## Default build remains independent

`BIVIDI_WITH_KIMERA_VIO` defaults to `OFF`. Normal Bividi configure/build/test does not call `find_package(kimera_vio)` and does not acquire Kimera, GTSAM, OpenCV, DBoW2, opengv, glog, or gflags through this gate.

## Real external link probe

Build Kimera-VIO and its dependency closure externally from the pinned revision, then expose its package config through `CMAKE_PREFIX_PATH` or `kimera_vio_DIR`.

Configure Bividi explicitly:

```bash
cmake -S . -B build-kimera \
  -DBIVIDI_WITH_KIMERA_VIO=ON \
  -DBIVIDI_KIMERA_VIO_REVISION=ce8c59b7b273ab5ac29db7e5572e1623760e19c7 \
  -DCMAKE_PREFIX_PATH=/path/to/kimera/install
```

Then build and run the probe:

```bash
cmake --build build-kimera --target bividi-kimera-link-probe --config Release
./build-kimera/bividi-kimera-link-probe
```

On multi-config generators, use the generator-specific executable path such as `build-kimera/Release/`.

The probe includes pinned public Kimera headers, asserts `VIO::Timestamp` is signed 64-bit, constructs `VIO::VioParams("")` using the upstream no-parse/default path, and links against the resolved external target. That is a compile/link/package-closure check only; it does not instantiate or run `StereoImuPipeline`.

## Revision assertion boundary

The pinned upstream package config does not encode its Git commit. Therefore `BIVIDI_KIMERA_VIO_REVISION` is an explicit operator/build provenance assertion, not a cryptographic derivation from the installed binary.

The external builder is responsible for producing the package from the exact pinned source revision. Bividi fails closed if the asserted revision is missing or differs from the frozen commit.

## Synthetic CI gate versus real external link

Normal Ubuntu/Windows CI runs `tests/test_kimera_cmake_gate.py`. It creates synthetic CMake packages that mimic the two pinned upstream target surfaces and proves:

- exact pin accepted;
- missing/wrong pin rejected;
- build-tree alias resolved;
- installed export resolved;
- unexpected target surfaces rejected;
- the link-probe source compiles and links against a minimal API-shaped fixture.

That synthetic test is **not** a claim that real Kimera/GTSAM was compiled or linked in normal CI.

A real external build must run the opt-in link probe above against the actual dependency closure.

## Next gate

After a real external link probe passes, the next issue may implement the runtime adapter/offline spike:

```text
#139 KimeraFeedDescription + translation plan
        -> external Kimera runtime adapter
        -> StereoImuPipeline feed
        -> backend output callback
        -> Bividi PoseObservation
```

That later gate must keep Frontend/Backend/LCD/Display tuning explicit, preserve #135 reset/reinitialize semantics, and avoid any AR0234 accuracy claim until measured #35/#8/#47 evidence exists.
