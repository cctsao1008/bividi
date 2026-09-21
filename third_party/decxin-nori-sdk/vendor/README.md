# DECXIN/Nori Windows x64 vendor bundle

The compact Windows x64 vendor bundle is tracked as five base64 text parts:

```text
DECXIN_Nori_Windows_x64_vendor_bundle.zip.b64.part00
DECXIN_Nori_Windows_x64_vendor_bundle.zip.b64.part01
DECXIN_Nori_Windows_x64_vendor_bundle.zip.b64.part02
DECXIN_Nori_Windows_x64_vendor_bundle.zip.b64.part03
DECXIN_Nori_Windows_x64_vendor_bundle.zip.b64.part04
```

`tools/install_decxin_nori_sdk.ps1` reconstructs the ZIP automatically after clone.

Reconstructed ZIP SHA-256:

```text
ff358cd7327f3246f9d5fcf58207bf1db46c384f4095b267c1d142d9fbc7daa5
```

Reconstructed ZIP size:

```text
510121 bytes
```

Derived byte-for-byte from selected files in the supplied `DECXIN_AR0234_Window..10.zip` archive (source SHA-256 `a603d88975c222a2891ca74c8c339509da755c279c0501f87e1c5a10df30c2f4`).

The reconstructed bundle is expanded into the ignored `../sdk/` working directory.
