# DECXIN / Nori SDK vendoring boundary

Bividi uses the DECXIN/Nori SDK for the optional native capture backend.

For this repository, **clone reproducibility is the primary requirement**: a developer cloning Bividi should not have to find a separate vendor ZIP before the Nori backend can be built. Therefore the repository workflow vendors the Windows x64 SDK subset that Bividi actually needs, while keeping the expanded working directory generated/ignored.

## Tracked vendor bundle

The repository expects this tracked file:

```text
third_party/decxin-nori-sdk/vendor/DECXIN_Nori_Windows_x64_vendor_bundle.zip
```

The bundle contains the Windows x64 build/runtime subset required by Bividi:

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

Known bundle SHA-256:

```text
5bfe5644f9df77aabeeb57ad4f43b59b9189d38298979024def51a0ee5d62f27
```

It was derived from the supplied AR0234 Windows SDK archive whose SHA-256 is:

```text
a603d88975c222a2891ca74c8c339509da755c279c0501f87e1c5a10df30c2f4
```

The full ~54 MiB vendor package is intentionally not required for Bividi: samples and files unrelated to the Windows x64 native backend do not belong in the normal clone path.

> Licensing note: the supplied package does not contain a visible package-root redistribution license. Keep the provenance/hash explicit and verify DECXIN/Norigine redistribution terms before treating this vendored subset as generally redistributable outside this project.

## Expanded local layout

The tracked bundle is expanded into:

```text
third_party/decxin-nori-sdk/sdk/
```

`./sdk/` is generated and ignored. A fresh clone reconstructs it from the tracked vendor bundle with:

```powershell
.\tools\install_decxin_nori_sdk.ps1
```

No external SDK path or download is required for the normal Windows x64 workflow.

The installer also accepts an explicitly supplied full vendor archive when validating a new vendor revision:

```powershell
.\tools\install_decxin_nori_sdk.ps1 `
  -Archive "C:\path\to\DECXIN_AR0234_Windows.zip" `
  -Force
```

Unknown full-archive hashes require `-AllowUnknownHash`.

## Build

After expansion:

```powershell
$SdkRoot = (Resolve-Path ".\third_party\decxin-nori-sdk\sdk").Path

cmake -S . -B build-nori `
  -DBIVIDI_WITH_NORI_SDK=ON `
  -DBIVIDI_NORI_SDK_ROOT="$SdkRoot"

cmake --build build-nori --config Release
```

Then stage the runtime DLL next to the generated executables:

```powershell
Copy-Item `
  "$SdkRoot\Libraries\win64\Nori_Xvision_API_x64.dll" `
  ".\build-nori\Release\" `
  -Force
```

Probe the physical device:

```powershell
.\build-nori\Release\bividi-nori-probe.exe
```

Use the reported device/mode indexes for `bividi-nori-characterize` as documented in `docs/characterization/nori-live-characterization.md`.

## Repository boundary

Tracked:

- the compact Windows x64 vendor bundle required by Bividi;
- vendor provenance and hashes;
- integration/build documentation;
- installer/validator logic;
- Bividi's SDK-facing adapter and characterization code.

Generated/ignored:

- `third_party/decxin-nori-sdk/sdk/` after expansion;
- capture output and hardware evidence artifacts.

This keeps the normal clone self-contained without importing the entire vendor SDK tree into Bividi source layout.