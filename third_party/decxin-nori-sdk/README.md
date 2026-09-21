# DECXIN / Nori SDK local dependency

Bividi can use the vendor-supplied DECXIN/Nori SDK for the optional native capture backend.

The vendor package is **not vendored into this public repository**. The supplied Windows archive does not contain a visible redistribution license at its package root, so headers, libraries, DLLs, sample sources, and executables must remain local until redistribution rights are established.

## Local layout

Install or extract the SDK under:

```text
third_party/decxin-nori-sdk/sdk/
```

Expected Windows x64 files include:

```text
sdk/
├── Includes/
│   ├── Nori_Xvision_API/
│   │   ├── Nori_Xvision_API.h
│   │   └── Nori_Xvision_FirmwareControl.h
│   └── Public/
├── Libraries/
│   ├── win32/
│   └── win64/
│       ├── Nori_Xvision_API_x64.lib
│       └── Nori_Xvision_API_x64.dll
└── Samples/
    ├── C++/
    └── c#/
```

The supplied package used during AR0234 bring-up has SHA-256:

```text
a603d88975c222a2891ca74c8c339509da755c279c0501f87e1c5a10df30c2f4
```

Use the repository installer/validator:

```powershell
.\tools\install_decxin_nori_sdk.ps1 -Archive "C:\path\to\DECXIN_AR0234_Windows.zip"
```

The script verifies the known archive hash by default, expands the package into the local `sdk/` directory, and validates the header/import-library/runtime-DLL layout. Use `-AllowUnknownHash` only for a deliberately accepted vendor package revision.

## Build

When the local SDK exists at the path above, Bividi auto-discovers it when the Nori backend is enabled:

```powershell
cmake -S . -B build-nori -DBIVIDI_WITH_NORI_SDK=ON
cmake --build build-nori --config Release
```

An explicit SDK root still takes precedence:

```powershell
cmake -S . -B build-nori `
  -DBIVIDI_WITH_NORI_SDK=ON `
  -DBIVIDI_NORI_SDK_ROOT="D:\vendor\Nori-sdk"
```

On Windows, CMake copies the matching Nori runtime DLL next to Bividi Nori executables after build so probe/characterization commands can run without a manual PATH edit.

## Runtime smoke test

```powershell
.\build-nori\Release\bividi-nori-probe.exe
```

Use the reported device/mode indexes for the live characterization harness described in `docs/characterization/nori-live-characterization.md`.

## Repository policy

Tracked here:

- integration documentation;
- installer/validator logic;
- CMake discovery and runtime staging;
- hashes/provenance for known vendor packages.

Not tracked here without an explicit redistribution grant:

- vendor headers;
- DLL/LIB files;
- vendor sample source or binaries;
- firmware payloads.

This boundary keeps `bividi_core` vendor-independent while making the optional hardware backend reproducible for developers who possess the SDK.
