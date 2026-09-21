# Tracked DECXIN/Nori Windows x64 bundle

This directory is the tracked vendor-payload slot for Bividi's Windows x64 Nori backend.

Expected file:

```text
DECXIN_Nori_Windows_x64_vendor_bundle.zip
```

Expected SHA-256:

```text
5bfe5644f9df77aabeeb57ad4f43b59b9189d38298979024def51a0ee5d62f27
```

Expected size:

```text
508953 bytes
```

The bundle is derived from the supplied `DECXIN_AR0234_Window..10.zip` archive (SHA-256 `a603d88975c222a2891ca74c8c339509da755c279c0501f87e1c5a10df30c2f4`) and contains only the headers, Windows x64 import/runtime library, and `Grab_Image.exe` needed for Bividi bring-up/reproducibility.

`tools/install_decxin_nori_sdk.ps1` expands this tracked bundle into the ignored `../sdk/` working directory.
