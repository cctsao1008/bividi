# DECXIN / Nori SDK local dependency

Bividi can use the vendor-supplied DECXIN/Nori SDK for the optional native capture backend.

The vendor package is **not vendored into this public repository**. The supplied Windows archive does not contain a visible redistribution license at its package root, so headers, libraries, DLLs, sample sources, and executables remain local until redistribution rights are established.

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

The current CMake contract keeps the vendor root explicit. With the local repository layout:

```powershell
$SdkRoot = (Resolve-Path ".\third_party\decxin-nori-sdk\sdk").Path

cmake -S . -B build-nori `
  -DBIVIDI_WITH_NORI_SDK=ON `
  -DBIVIDI_NORI_SDK_ROOT="$SdkRoot"

cmake --build build-nori --config Release
```

An SDK installed elsewhere can be supplied through the same `BIVIDI_NORI_SDK_ROOT` cache variable.

## Windows runtime DLL

The vendor runtime DLL must be discoverable when a Nori executable starts. The simplest local setup is:

```powershell
Copy-Item `
  .\third_party\decxin-nori-sdk\sdk\Libraries\win64\Nori_Xvision_API_x64.dll `
  .\build-nori\Release\
```

Then run:

```powershell
.\build-nori\Release\bividi-nori-probe.exe
```

Use the reported device/mode indexes for the live characterization harness described in `docs/characterization/nori-live-characterization.md`.

## Repository policy

Tracked here:

- integration documentation;
- installer/validator logic;
- hashes/provenance for known vendor packages;
- Bividi's SDK-facing adapter and characterization code.

Not tracked here without an explicit redistribution grant:

- vendor headers;
- DLL/LIB files;
- vendor sample source or binaries;
- firmware payloads.

This boundary keeps `bividi_core` vendor-independent while making the optional hardware backend reproducible for developers who possess the SDK.
