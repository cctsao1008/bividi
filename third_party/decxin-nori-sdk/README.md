# DECXIN / Nori SDK vendoring boundary

Bividi uses the DECXIN/Nori SDK for the optional native capture backend.

For this repository, clone reproducibility is the primary requirement: a developer cloning Bividi should not need to locate a separate DECXIN ZIP before the Nori backend can be built. The repository therefore tracks the compact Windows x64 SDK subset required by Bividi, while keeping the expanded working directory generated/ignored.

## Tracked vendor bundle

Expected tracked file:

```text
third_party/decxin-nori-sdk/vendor/DECXIN_Nori_Windows_x64_vendor_bundle.zip
```

The bundle contains:

```text
Includes/Nori_Xvision_API/Nori_Xvision_API.h
Includes/Nori_Xvision_API/Nori_Xvision_FirmwareControl.h
Includes/Public/Nori_public.h
Includes/Public/Nori_Error_Define.h
Libraries/win64/Nori_Xvision_API_x64.lib
Libraries/win64/Nori_Xvision_API_x64.dll
Samples/C++/x64/Release/Grab_Image.exe
BIVIDI_VENDOR_PROVENANCE.txt
```

Bundle SHA-256:

```text
ff358cd7327f3246f9d5fcf58207bf1db46c384f4095b267c1d142d9fbc7daa5
```

Bundle size:

```text
510121 bytes
```

It was derived from the supplied AR0234 Windows SDK archive:

```text
DECXIN_AR0234_Window..10.zip
SHA-256: a603d88975c222a2891ca74c8c339509da755c279c0501f87e1c5a10df30c2f4
```

The full ~54 MiB package is not required by Bividi's Windows x64 backend.

> Licensing/provenance: the supplied package does not expose a package-root redistribution license. Keep the source/bundle hashes explicit and confirm vendor redistribution terms as appropriate.

## Expand after clone

```powershell
.\tools\install_decxin_nori_sdk.ps1
```

This expands the tracked bundle into:

```text
third_party/decxin-nori-sdk/sdk/
```

The expanded `sdk/` directory is ignored because it is generated from the tracked bundle.

## Build

```powershell
$SdkRoot = (Resolve-Path ".\third_party\decxin-nori-sdk\sdk").Path

cmake -S . -B build-nori `
  -DBIVIDI_WITH_NORI_SDK=ON `
  -DBIVIDI_NORI_SDK_ROOT="$SdkRoot"

cmake --build build-nori --config Release

Copy-Item `
  "$SdkRoot\Libraries\win64\Nori_Xvision_API_x64.dll" `
  ".\build-nori\Release\" `
  -Force

.\build-nori\Release\bividi-nori-probe.exe
```

`BIVIDI_NORI_SDK_ROOT` remains explicit so the vendor dependency does not leak into `bividi_core`.
