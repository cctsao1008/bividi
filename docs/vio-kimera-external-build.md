# Kimera-VIO external package/link gate

This document covers the opt-in external package/link boundary for the Kimera-VIO spike (#142) and its evidence-producing execution harness (#145).

The exact upstream revision is frozen by #137/#139:

```text
MIT-SPARK/Kimera-VIO@ce8c59b7b273ab5ac29db7e5572e1623760e19c7
```

This gate does not adopt Kimera-VIO as a product backend and does not establish VIO accuracy.

## Why this is a standalone CMake entrypoint

The external package/link probe is intentionally configured from:

```text
cmake/kimera-external/
```

rather than from Bividi's normal root configure. This keeps the default repository build completely independent of Kimera/GTSAM. Normal `cmake -S . -B build ...` therefore never calls `find_package(kimera_vio)` because of this gate.

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

## One-command real external evidence run

Build Kimera-VIO and its dependency closure externally from the pinned revision. Keep the local Kimera source checkout at the exact pinned commit and expose the matching package through `CMAKE_PREFIX_PATH` or `kimera_vio_DIR`.

From the Bividi repository, run:

```bash
python tools/run_kimera_external_link_probe.py \
  --kimera-source /path/to/Kimera-VIO \
  --cmake-prefix /path/to/kimera/install \
  --build-dir artifacts/vio/kimera-link-build \
  --evidence-out artifacts/vio/kimera-link-evidence.json \
  --assert-package-built-from-source
```

Use `--kimera-vio-dir /path/to/lib/cmake/kimera_vio` instead of or in addition to `--cmake-prefix` when appropriate.

The assertion flag is intentionally explicit. The runner verifies the local source tree's `git rev-parse HEAD` against the exact pin, but the installed/build-tree package does not cryptographically identify which source checkout produced it. Therefore the emitted package-to-source binding is recorded as:

```text
operator_asserted
```

and `source_binding_verified` remains `false`. The runner never upgrades that assertion into a stronger provenance claim.

The runner records whether the source checkout is dirty. Dirty state does not automatically fail the link probe because it is evidence about the source tree, but it remains visible in the artifact and must be reviewed before interpreting the result.

## Evidence artifact

A completed run writes:

```text
bividi.vio.kimera_external_link_evidence.v1
```

The artifact records the exact frozen upstream revision, verified local source HEAD, dirty state, package paths, package/source binding level, host/CMake metadata, configure/build/probe commands and return codes, output hashes/tails, probe-reported pin, resolved target kind, final status, and an explicit claim ceiling.

A real successful run has status:

```text
PASS_REAL_EXTERNAL_LINK
```

This means the externally supplied package passed the public-header/link probe under the recorded operator assertion. It still does **not** mean `StereoImuPipeline` has been instantiated or that VIO has produced a valid pose.

Input/source rejection returns exit code `2`. A completed configure/build/probe failure returns exit code `3`. Success returns `0`.

## Manual CMake path

The same boundary can still be exercised manually:

```bash
cmake -S cmake/kimera-external -B build-kimera \
  -DBIVIDI_KIMERA_VIO_REVISION=ce8c59b7b273ab5ac29db7e5572e1623760e19c7 \
  -DCMAKE_PREFIX_PATH=/path/to/kimera/install
cmake --build build-kimera --target bividi-kimera-link-probe --config Release
ctest --test-dir build-kimera -C Release -R '^bividi_kimera_external_link_probe$' -V
```

The probe includes pinned public Kimera headers, asserts `VIO::Timestamp` is signed 64-bit, constructs `VIO::VioParams("")` using the upstream no-parse/default path, and links against the resolved external target.

## Revision and provenance boundary

The pinned upstream package config does not encode its Git commit. #145 therefore separates three facts instead of conflating them:

1. the local Kimera source checkout revision is machine-verified with Git;
2. the external package successfully compiles/links the pinned public API probe;
3. the claim that the package was built from that verified source checkout is explicitly operator asserted.

No artifact field says the package/source binding is cryptographically verified.

## Synthetic CI versus real external link

Normal Ubuntu/Windows CI does not install Kimera/GTSAM. It creates temporary API-shaped CMake package fixtures and a temporary Git repository, then exercises the same standalone CMake entrypoint and the same evidence runner mechanics.

Synthetic success is emitted only as:

```text
PASS_SYNTHETIC_FIXTURE
```

and uses `source_binding=synthetic_fixture`. The synthetic source revision is deliberately not treated as the frozen upstream commit. This prevents normal CI from being mistaken for real external evidence.

The older #142 CMake-gate test also continues to verify exact pin enforcement, both target spellings, and fail-closed behavior for unexpected package surfaces.

## Next gate

After `PASS_REAL_EXTERNAL_LINK` is produced on a real external dependency environment, the next issue may implement the runtime adapter/offline spike:

```text
#139 KimeraFeedDescription + translation plan
        -> external Kimera runtime adapter
        -> StereoImuPipeline feed
        -> backend output callback
        -> Bividi PoseObservation
```

That later gate must keep Frontend/Backend/LCD/Display tuning explicit, preserve #135 reset/reinitialize semantics, and avoid any AR0234 accuracy claim until measured #35/#8/#47 evidence exists.
