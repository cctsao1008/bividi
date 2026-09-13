# Waveshare AR0144 Stereo USB Camera (A)

Status: **pre-hardware product baseline — Issue #3**  
Access date: **2026-09-14**

This document separates vendor claims, generic USB-camera guidance, engineering inference, unknowns, and future measured behavior. It is not a substitute for the real device characterization in Issues #4-#6.

## Evidence classes

```text
VENDOR CLAIM               product-specific statement from Waveshare
DOCUMENTED GENERIC         generic behavior from Waveshare USB Camera Common Manual
SENSOR FACT                AR0144 sensor-level fact from onsemi
INFERENCE                  engineering interpretation; not measured
UNVERIFIED                 important property not yet established
MEASURED                   direct Bividi measurement from the physical unit
```

`MEASURED` is intentionally empty until the camera arrives.

## 1. Identity

| Property | Value | Evidence | Notes |
|---|---|---|---|
| Product | AR0144 Stereo USB Camera (A) | VENDOR CLAIM | Waveshare part name |
| Waveshare SKU | 32695 | VENDOR CLAIM | Current product page |
| Sensor | AR0144 | VENDOR CLAIM | Dual-camera module; exact sensor ordering/variant still to inspect |
| Sensor native class | 1.0 MP, 1280 × 800 active array, 1/4-inch, global shutter | SENSOR FACT | onsemi AR0144CS product information |
| Product marketing pixel label | 2MP stereo module | VENDOR CLAIM | Current product page |
| Wiki pixel label | 1MP | VENDOR CLAIM | Current wiki; conflicts with product-page marketing label |

### Pixel-label interpretation

The current product page calls the module **2MP**, while the AR0144 sensor itself is a **1.0 MP 1280 × 800** sensor and the Waveshare wiki labels the camera **1MP**. A plausible interpretation is that “2MP” is an aggregate stereo marketing label for two approximately 1MP sensors, but Waveshare does not clearly state that interpretation in the cited material.

**Classification: INFERENCE — do not encode as a device contract.**

## 2. Optics and mechanics

| Property | Vendor value | Evidence |
|---|---:|---|
| Sensor size | 1/4 inch | VENDOR CLAIM |
| Aperture | F/2.2 | VENDOR CLAIM |
| Focal length (EFL) | 2.88 mm | VENDOR CLAIM |
| FOV | 74° diagonal / 65° horizontal / 43° vertical | VENDOR CLAIM |
| Focus | Fixed focus | VENDOR CLAIM |
| Distortion | < 0.2% | VENDOR CLAIM |
| IR filter | 650 nm | VENDOR CLAIM |
| Baseline | 52 mm | VENDOR CLAIM |
| Module dimensions | 66.00 × 30.00 × 17.72 mm | VENDOR CLAIM |
| Operating voltage | 5 V ± 5% | VENDOR CLAIM |

Vendor distortion and baseline values are nominal product claims. Stereo calibration in Issue #8 must measure the actual intrinsic/extrinsic geometry of the purchased unit.

## 3. Shutter and synchronization

| Property | Statement | Evidence | Status |
|---|---|---|---|
| Shutter | Global shutter | VENDOR CLAIM + SENSOR FACT | Sensor capability is independently consistent with onsemi AR0144 documentation |
| Stereo synchronization | “Frame-synchronized stereo output” / synchronized driving, both image channels output in the same frame | VENDOR CLAIM | Mechanism and timing quality are not published in the reviewed material |
| Exposure skew | Unknown | UNVERIFIED | Measure/bound in #6 |
| Long-run pairing stability | Unknown | UNVERIFIED | Measure in #6 |
| Shared trigger/clock implementation | Unknown | UNVERIFIED | Do not infer from the phrase “same frame” |

`global shutter != proven stereo exposure simultaneity`.

Issue #6 owns the measured interpretation of synchronization.

## 4. Host interface

| Property | Statement | Evidence |
|---|---|---|
| Physical/host interface | USB 2.0 Type-C | VENDOR CLAIM |
| Driver model | Vendor describes plug-and-play / driver-free operation | VENDOR CLAIM |
| Supported OS | Windows, Linux, macOS | VENDOR CLAIM (wiki) |
| Formats | MJPG, YUY2 | VENDOR CLAIM |
| DSP controls | Auto gain / exposure / white balance | VENDOR CLAIM (wiki) |

The Waveshare **USB Camera Common Manual** additionally documents generic host use:

- on PC, connect the USB camera and test with AMCap;
- on Raspberry Pi/Linux, successful enumeration may expose `/dev/video0`;
- its example uses `mjpg_streamer` with `input_uvc.so`.

These are **DOCUMENTED GENERIC** USB-camera instructions. They support the expectation of a UVC/V4L2-style host path, but they do **not** establish this stereo module's exact node count, descriptor topology, endpoint layout, packing, or timing.

## 5. Current Waveshare mode claims

### Current product page

Current product-page claims include:

**Static image**

```text
2560 × 720 (1280 × 720)
```

**MJPG**

```text
30 FPS  2560 × 720
60 FPS  1600 × 600
60 FPS  1280 × 720
60 FPS  800 × 600
60 FPS  640 × 480
120 FPS 640 × 352
120 FPS 640 × 360
```

**YUY2**

```text
5 FPS   2560 × 720
10 FPS  1280 × 720
20 FPS  800 × 600
30 FPS  640 × 480
```

Classification: **VENDOR CLAIM**. Issue #4 must compare these values with descriptors and actual capture behavior.

### Current wiki

The wiki currently lists a different mode table, including:

```text
MJPG 60 FPS 2560 × 720
```

and additional modes such as `1600 × 600`, `1280 × 480`, `1280 × 360`, and `1280 × 712` with different frame rates.

Classification: **VENDOR CLAIM WITH INTERNAL DOCUMENTATION CONFLICT**.

### Product-comparison table

The current Waveshare product page comparison table describes the AR0144 stereo camera as:

```text
1MP | AR0144 | 2560 × 800 | Global shutter | frame-synchronized stereo output
```

This conflicts with the same product page's detailed `2560 × 720` static/video specification.

Classification: **VENDOR CLAIM WITH INTERNAL DOCUMENTATION CONFLICT**.

### Bividi rule

Do not reconcile these tables by choosing one silently.

```text
vendor table != UVC descriptor != stable captured behavior
```

Issue #4 establishes the host-visible modes; Issue #5 establishes the actual stereo packing and per-eye geometry.

## 6. Sensor-level facts from onsemi

The onsemi AR0144CS product information states:

- 1/4-inch CMOS digital image sensor;
- 1.0 MP;
- active array 1280H × 800V;
- global-shutter pixel design;
- functions including auto exposure control, windowing, row/column skip, pixel binning, video and single-frame modes.

An onsemi AR0144 IAS evaluation-module manual also lists a representative AR0144 module at up to 60 fps at 1280 × 800 with raw output. That IAS module is **not** the Waveshare USB stereo product, so its module/lens/interface values must not be transferred to Bividi's camera profile. It is useful only as sensor-family context.

## 7. Explicit unknowns before hardware arrival

The following remain **UNVERIFIED**:

| Question | Owning issue |
|---|---|
| Actual VID/PID/product strings | #4 |
| Negotiated USB speed (HS/FS in the real host path) | #4 |
| Number of UVC interfaces/video nodes | #4 |
| Endpoint types/sizes/intervals | #4 |
| Exact UVC descriptor mode table | #4 |
| Actual stable FPS per mode | #4 / #10 |
| Whether `2560 × 720` is side-by-side packing | #5 |
| Per-eye crop/resolution for every exposed mode | #5 |
| Left/right ordering | #5 |
| MJPEG/YUY2 packing details | #5 |
| Bridge/DSP/USB-controller IC identity | hardware inspection; not required by core architecture |
| Synchronization mechanism | #6 |
| Exposure timing skew | #6 |
| Drop/duplicate/misalignment behavior | #6 / #10 |
| Actual lens intrinsics/distortion | #8 |
| Actual stereo baseline/extrinsics | #8 |
| Depth accuracy/useful range | #9 / #10 |

## 8. Engineering inferences kept provisional

### Likely composite stereo frame

The product page writes the static mode as `2560 × 720 (1280 × 720)`. This strongly suggests a two-view composite in which two 1280 × 720 images are transported together, but the reviewed vendor text does not explicitly say “side-by-side,” and the device has not been measured.

**Classification: INFERENCE.** Issue #5 must prove the layout.

### USB bandwidth explains format/rate asymmetry

The vendor mode table gives much lower full-resolution frame rate for uncompressed YUY2 than for MJPEG. That pattern is consistent with USB bandwidth pressure and MJPEG compression, but Bividi does not use it to infer endpoint topology or actual achieved throughput.

**Classification: INFERENCE.** Issues #4 and #10 own measurement.

## 9. Sources

### Product-specific

- Waveshare product page: https://www.waveshare.com/product/raspberry-pi/cameras/ar0144-stereo-usb-camera-a.htm
- Waveshare wiki: https://www.waveshare.com/wiki/AR0144_Stereo_USB_Camera_%28A%29

### Sensor

- onsemi AR0144CS product overview: https://www.onsemi.com/parametrics/AR0144CS/create-overview-pdf
- onsemi AR0144CS IAS module manual (sensor-family context only): https://www.onsemi.com/pub/Collateral/EVBUM2741-D.PDF

### Generic USB camera guidance

- Waveshare `USB_Camera_Common_User_Manual_EN.pdf` supplied with this research project.

## 10. Pre-hardware verdict

```text
FIRST SENSOR FAMILY: AR0144                         ESTABLISHED
GLOBAL-SHUTTER SENSOR CAPABILITY:                   ESTABLISHED
52 mm BASELINE:                                     VENDOR CLAIM
FRAME-SYNCHRONIZED STEREO OUTPUT:                   VENDOR CLAIM
USB 2.0 TYPE-C:                                     VENDOR CLAIM
MJPG / YUY2:                                        VENDOR CLAIM
EXACT UVC TOPOLOGY:                                 UNKNOWN
EXACT STEREO PACKING:                               UNKNOWN
FULL-RES STABLE FPS:                                UNKNOWN / VENDOR DOCS CONFLICT
EXPOSURE-LEVEL SYNC QUALITY:                        UNKNOWN
FACTORY CALIBRATION DATA:                           NOT ESTABLISHED
BRIDGE / DSP IC:                                    UNKNOWN
MEASURED DEVICE BEHAVIOR:                           PENDING HARDWARE
```

The next authoritative step is Issue #4 after the camera arrives.
