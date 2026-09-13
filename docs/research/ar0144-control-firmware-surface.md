# Waveshare AR0144 USB Control and Firmware-Access Surface

Status: **public-evidence audit — Issue #26**  
Date: 2026-09-14

## 1. Research question

What can a host actually control on the Waveshare **AR0144 Stereo USB Camera (A)**, and is firmware modification a public/supported workflow?

The central distinction is:

```text
AR0144 image-sensor capability
!=
Waveshare USB-module exposed capability
```

The AR0144 sensor itself is programmable. The purchased Waveshare product places two sensors behind an onboard DSP/USB bridge and exposes USB as the documented host interface. A sensor feature therefore does not become a usable Bividi feature unless the module exposes it through USB or another accessible interface.

## 2. Evidence classes

This note uses four classes:

- **SUPPORTED / DOCUMENTED** — Waveshare explicitly exposes or documents the capability.
- **LIKELY / CORROBORATED** — multiple public implementations or standard UVC behavior support the expectation, but our unit has not yet been measured.
- **UNKNOWN / PROBE** — technically plausible and worth enumerating on the physical unit, but no product-specific public evidence was found.
- **NOT PUBLICLY SUPPORTED / FOUND** — the public Waveshare resources audited do not provide the necessary SDK, firmware, protocol, updater, or programming instructions. This does **not** prove technical impossibility.

## 3. Current capability matrix

| Capability | Current classification | Evidence / interpretation |
| --- | --- | --- |
| USB2.0 UVC video streaming | SUPPORTED / DOCUMENTED | Waveshare documents USB2.0 Type-C, driver-free operation, MJPG and YUY2. |
| Resolution / frame-interval selection | SUPPORTED / DOCUMENTED | Product/wiki expose multiple MJPG/YUY2 modes, although the published mode tables conflict and therefore must be measured. |
| Brightness / contrast controls | SUPPORTED AT HOST-CONTROL LEVEL, EXACT RANGE UNKNOWN | Waveshare FAQ explicitly discusses brightness/contrast parameter control and recommends Linux + V4L2 when Mac/OpenCV cannot set them. |
| Auto gain / exposure / white balance | DOCUMENTED DSP BEHAVIOR | Waveshare wiki lists DSP auto gain/exposure/white balance. Whether manual counterparts are exposed over UVC is not documented. |
| Manual exposure / gain / white balance | UNKNOWN / PROBE | Plausible UVC controls, but no product-specific public control list was found. Enumerate rather than assume. |
| UVC Extension Unit / vendor USB controls | UNKNOWN / PROBE | Common in USB-camera controller ecosystems, but no Waveshare AR0144 XU GUID, protocol, SDK, or control map was found. |
| Direct AR0144 register read/write from host | NOT PUBLICLY SUPPORTED / FOUND | AR0144 has a two-wire sensor-control interface, but Waveshare does not document a USB-to-sensor-register command path. |
| External trigger input | SENSOR SUPPORT EXISTS; MODULE ACCESS UNKNOWN | onsemi AR0144 IAS documentation exposes TRIGGER at sensor/module level. Waveshare exposes no documented trigger connector or host trigger API for this product. |
| Stereo-sync firmware/timing modification | NOT PUBLICLY SUPPORTED / FOUND | Waveshare claims synchronized same-frame output but provides no timing-control SDK or synchronization firmware interface. |
| Bridge/DSP firmware source | NOT PUBLICLY SUPPORTED / FOUND | No public source tree or build SDK found in Waveshare resources. |
| Firmware image / updater / burner | NOT PUBLICLY SUPPORTED / FOUND | No model-specific firmware package, updater, burner, recovery image, or flashing guide found in Waveshare resources. |
| Firmware backup / recovery path | UNKNOWN | Must identify the controller and nonvolatile storage before considering any destructive experiment. |
| Serial-flash / EEPROM configuration | UNKNOWN / PROBE | Generic UVC-controller families often use external NVM, but no product-specific identification has been established. |

## 4. What Waveshare actually documents

Official product material describes the module as a plug-and-play USB2.0 camera with:

- two AR0144 global-shutter sensors;
- synchronized same-frame stereo output;
- 52 mm baseline;
- USB2.0 Type-C host interface;
- MJPG and YUY2 formats;
- fixed-focus optics;
- onboard DSP behavior including automatic gain, exposure and white balance.

The official wiki uses ordinary host camera applications (Windows Camera/AMCap), Linux camera tooling and OpenCV examples. Its FAQ specifically says that brightness/contrast parameter setting may fail on Mac/OpenCV and recommends Linux with V4L2.

This is meaningful evidence that **host-side camera control is expected through the normal UVC/V4L2 surface**. It is not evidence of a public low-level sensor-register API.

### Public Waveshare resources audited

- Product page: https://www.waveshare.com/ar0144-stereo-usb-camera-a.htm
- Wiki: https://www.waveshare.com/wiki/AR0144_Stereo_USB_Camera_(A)
- Product resource links visible from the wiki: generic USB camera user manual, AMCap, mjpg-streamer and common USB-camera/OpenCV examples.

No AR0144-specific firmware SDK, firmware image, bootloader procedure, register-access API, UVC Extension Unit specification, EEPROM map, programmer or recovery tool was found in the public resource set.

## 5. Sensor capability is larger than the USB-module interface

The onsemi AR0144 itself is not a sealed device. Public sensor/module documentation shows a programmable sensor architecture and pins/signals including serial control, RESET and TRIGGER.

Relevant source:

- onsemi AR0144CS IAS Module evaluation/manual material: https://www.onsemi.com/

This means the physical sensor can support lower-level control in a design where those signals are exposed. It does **not** show that the Waveshare USB board routes those controls to the host.

Conceptually:

```text
AR0144-L ---- sensor control/trigger ----\
                                        onboard DSP / bridge ---- USB UVC ---- host
AR0144-R ---- sensor control/trigger ----/

                 hidden/internal boundary
```

For Bividi, the useful question is therefore not "can AR0144 do X?" but "does this Waveshare bridge expose X?"

## 6. Could the firmware still be technically modifiable?

Yes, **technically possible is not the same as publicly supported**.

The wider USB-camera industry includes controllers whose architecture stores firmware/configuration in serial flash and supports vendor-specific UVC Extension Units or USB firmware upgrade paths. Sonix is one concrete example:

- Sonix controller documentation for some families describes loading VID/PID, strings, UVC parameter definitions and extended firmware from external serial flash, with firmware upgrade through the PC/USB path.
- Public Sonix-based camera projects expose vendor Extension Unit controls.
- Other USB-camera vendors publish burner utilities for their own modules.

References:

- Sonix SN9C291B product information: https://www.sonix.com.tw/
- Kurokesu Sonix Extension Unit tooling: https://github.com/Kurokesu/C1_SONIX_Test_AP
- Arducam USB UVC firmware-burning documentation: https://docs.arducam.com/UVC-Camera/Firmware-Burning/

There is also third-party camera-solution evidence that AR0144 has been paired in the industry with Sonix controllers such as SN9C5259AFG and SN9C292BIG:

- https://www.camemake.eu/usb-camera-modules

However:

> **There is currently no evidence that the Waveshare AR0144 Stereo USB Camera (A) uses those Sonix parts.**

AR0144 compatibility in another vendor's controller matrix is only a clue about what kinds of architectures exist. It must not be used to identify the Waveshare controller.

## 7. PCB evidence

Waveshare's official product photographs show:

- the USB-C connector as the only documented user-facing electrical interface;
- a central controller/DSP package between the two optical channels;
- additional support ICs and power rails;
- no documented user programming header, external sensor-control connector, or trigger connector.

Official product image source:

- https://www.waveshare.com/ar0144-stereo-usb-camera-a.htm

The visible IC markings are not sufficiently established from public photographs to identify the controller with confidence. A nearby small IC must not be labelled "flash" or "EEPROM" without reading its marking or tracing the board.

## 8. Important documentation inconsistency

Public Waveshare pages are internally inconsistent:

- the current product page lists 2560x720 MJPG at 30 FPS;
- the wiki lists 2560x720 MJPG at 60 FPS;
- the selection table describes the AR0144 entry with a "best resolution" of 2560x800.

Therefore published specifications are hypotheses/marketing evidence, not the host contract. Bividi must let UVC descriptors and measured captures decide the actual modes.

## 9. Bring-up probes required by Issue #4

When the physical unit is available, the first USB audit must capture all of the following before writing a device backend:

```text
USB identity
  VID/PID
  manufacturer/product/serial strings
  negotiated bus speed

USB/UVC structure
  configuration/interface descriptors
  VideoControl + VideoStreaming descriptors
  Processing Units
  Camera Terminal controls
  Extension Unit descriptors / GUIDs, if any
  endpoint topology

V4L2/UVC controls
  full control list and ranges
  control menu values
  auto/manual interactions
  read-back after each write

stream negotiation
  enumerated formats/modes/frame intervals
  requested mode
  negotiated/read-back mode
  actual captured geometry/FPS
```

Recommended Linux evidence capture includes `lsusb -v`, `v4l2-ctl --all`, `v4l2-ctl --list-formats-ext`, and `v4l2-ctl --list-ctrls-menus`.

If AMCap, V4L2 or another tool exposes a control not represented as a standard UVC control, USB control traffic can then be inspected with usbmon/Wireshark to determine whether a vendor-specific request or Extension Unit is involved.

## 10. Controller-identification gate

Before any firmware-oriented work, identify:

1. USB VID/PID and manufacturer/product strings;
2. all UVC Extension Units;
3. central controller IC marking from a macro/microscope photograph;
4. markings of nearby nonvolatile-memory candidates;
5. whether a documented vendor SDK/burner matches that exact controller and board configuration.

Only after those facts exist should Bividi open a firmware-access experiment issue.

## 11. No-flash / no-burn rule

Until the controller is identified and a non-destructive backup/recovery path is demonstrated:

```text
DO NOT
  burn firmware
  erase serial flash / EEPROM
  run a generic vendor burner in write mode
  write unknown Extension Unit commands
  change persistent USB descriptors
```

A generic burner that recognizes a controller family is not proof that its firmware image, board configuration, sensor tables or GPIO map are compatible with the Waveshare module. A wrong image may remove normal UVC enumeration and make recovery substantially harder.

Read-only enumeration and USB traffic observation are the correct first stage.

## 12. Research conclusion

For normal supported use, treat the Waveshare board as a **sealed UVC stereo appliance with a measurable control surface**.

The strongest current conclusion is:

```text
public/supported surface
    UVC video + mode selection
    some camera controls through UVC/V4L2

not publicly exposed
    AR0144 register programming
    trigger/sync timing programming
    bridge/DSP firmware development
    firmware backup/burn/recovery workflow

possible but unproven
    vendor Extension Unit
    hidden controller commands
    USB firmware upgrade mechanism
    external flash/EEPROM configuration
```

Therefore Bividi should not assume firmware modification is available, but it should explicitly **probe for hidden/extended USB control surfaces** during Issue #4 rather than prematurely declaring them impossible.
