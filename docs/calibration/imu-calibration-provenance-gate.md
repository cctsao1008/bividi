# IMU Calibration Session Provenance Gate

Owner: Issue #47  
Applies to: Bividi IMU stationary, Allan, six-position, and controlled-rotation evidence  
Status: dependency-free manifest/gate implemented; measured specimen manifests pending delivered hardware

## Purpose

The IMU calibration tools intentionally solve different observability problems. That creates a systems risk if their outputs are later combined even though they were captured with different hardware, firmware, camera mode, IMU range, ODR, or filtering.

The provenance gate makes the compatibility claim explicit and hash-binds the evidence before values are promoted into `bividi.calibration.imu.v1`.

```text
stationary evidence
Allan evidence
six-position evidence
controlled gyro evidence
        ↓
shared specimen/configuration manifest
        ↓
SHA-256 + recorder-summary compatibility checks
        ↓
full-IMU evidence gate
        ↓
promotion gate
        ↓
reviewed IMU calibration artifact
```

The gate prevents accidental mixing. It does **not** prove that an operator-entered sensor register setting is physically true; `configuration_source` must state how range/ODR/filter settings were established.

## Durable manifest

Schema:

```text
calibration/schemas/imu-calibration-session-v1.schema.json
```

Schema identifier:

```text
bividi.calibration.imu_session_manifest.v1
```

The manifest binds:

```text
session ID / creation time
specimen model + serial
Nori SDK version
device type
ISP version
FPGA version
camera mode / geometry / nominal FPS / transport
IMU model / target frame
accelerometer range
gyroscope range
ODR
accelerometer filter
gyroscope filter
configuration source
capture roles + SHA-256
analysis roles + SHA-256 + report schema
synthetic vs measured provenance
```

## Why recorder summaries are authoritative for host/device provenance

`bividi-nori-imu-record` writes both:

```text
<PREFIX>.imu.csv
<PREFIX>.json
```

The summary JSON already records the connected device serial, Nori SDK version, device/ISP/FPGA versions and selected video mode. The provenance tool reads those fields rather than asking the operator to retype them.

Every capture added to one manifest must report exactly the same observed device provenance and camera mode. If one trace differs, manifest creation fails and the evidence should be split into another session.

The raw CSV and recorder summary are both SHA-256 bound.

## Operator-declared IMU configuration

The current Nori recorder does not expose a verified ICM-42688 register snapshot covering range, ODR and digital filtering. Those fields therefore remain explicit experiment declarations:

```text
--accel-range-g
--gyro-range-dps
--odr-hz
--accel-filter
--gyro-filter
--configuration-source
```

`configuration_source` should say how the setting was verified, for example a known firmware configuration/register readback procedure. Do not write `unknown`, `TBD`, or a vendor-demo assumption and then use the promotion gate.

A future register-readback path may replace some operator declarations with captured hardware provenance, but it should preserve the same manifest boundary.

## Capture roles for a full IMU evidence set

The `full-imu` and `promotion` profiles require these roles:

```text
stationary
allan_stationary

sixpos_plus_x
sixpos_minus_x
sixpos_plus_y
sixpos_minus_y
sixpos_plus_z
sixpos_minus_z

gyro_stationary
gyro_plus_x
gyro_minus_x
gyro_plus_y
gyro_minus_y
gyro_plus_z
gyro_minus_z
```

The same physical recording may be bound under more than one role when the experiment intentionally reuses it. In that case the hashes will be identical, which is explicit evidence rather than an implicit assumption.

The required analysis roles are:

```text
stationary
allan
six_position
gyro_rotation
```

Known roles also validate their report schema identifiers, preventing a random JSON file from satisfying a named analysis slot.

## Create a manifest

Example after all captures/reports exist:

```bash
python tools/imu_calibration_provenance.py create \
  --output ar0234_imu_session.manifest.json \
  --session-id ar0234-unit01-imu-20260917 \
  --device-model "DECXIN AR0234 stereo module" \
  --imu-model "ICM-42688-P" \
  --imu-frame bividi_imu \
  --accel-range-g <VERIFIED_RANGE> \
  --gyro-range-dps <VERIFIED_RANGE> \
  --odr-hz <VERIFIED_ODR> \
  --accel-filter "<VERIFIED_ACCEL_FILTER_CONFIG>" \
  --gyro-filter "<VERIFIED_GYRO_FILTER_CONFIG>" \
  --configuration-source "<HOW THE CONFIGURATION WAS VERIFIED>" \
  --capture stationary=stationary.json \
  --capture allan_stationary=allan_long.json \
  --capture sixpos_plus_x=sixpos_px.json \
  --capture sixpos_minus_x=sixpos_nx.json \
  --capture sixpos_plus_y=sixpos_py.json \
  --capture sixpos_minus_y=sixpos_ny.json \
  --capture sixpos_plus_z=sixpos_pz.json \
  --capture sixpos_minus_z=sixpos_nz.json \
  --capture gyro_stationary=gyro_static.json \
  --capture gyro_plus_x=gyro_px.json \
  --capture gyro_minus_x=gyro_nx.json \
  --capture gyro_plus_y=gyro_py.json \
  --capture gyro_minus_y=gyro_ny.json \
  --capture gyro_plus_z=gyro_pz.json \
  --capture gyro_minus_z=gyro_nz.json \
  --analysis stationary=stationary.analysis.json \
  --analysis allan=allan.analysis.json \
  --analysis six_position=sixpos.analysis.json \
  --analysis gyro_rotation=gyro.analysis.json \
  --profile full-imu
```

Each `--capture ROLE=...` points to the `bividi-nori-imu-record` **summary JSON**, not directly to the CSV. The tool follows the summary's `artifact` field, verifies that the raw trace exists, and binds both files.

## Verification profiles

### `basic`

Checks structure, recorder provenance consistency, report-schema mapping, file sizes, and SHA-256 bindings. It does not require every calibration experiment.

```bash
python tools/imu_calibration_provenance.py verify session.manifest.json
```

### `full-imu`

Additionally requires the complete capture/analysis role set and rejects placeholder IMU configuration text.

```bash
python tools/imu_calibration_provenance.py verify \
  session.manifest.json \
  --profile full-imu
```

This profile is useful for synthetic CI fixtures and measured experiments.

### `promotion`

Adds the final provenance condition:

```text
provenance.kind == measured
```

and rejects placeholder specimen/device fields.

```bash
python tools/imu_calibration_provenance.py verify \
  session.manifest.json \
  --profile promotion
```

A `promotion` PASS means the evidence bundle is structurally complete, internally compatible according to recorded metadata, and unchanged according to its hashes. It does **not** mean the calibration values themselves meet an accuracy requirement; numerical quality acceptance remains a separate engineering review.

## Hash verification and archived bundles

By default, verification reopens every capture summary, raw trace and analysis JSON, checks file size + SHA-256, and rechecks the recorder's observed device/mode fields.

Manifest paths are stored relative to the manifest where practical. If an archived bundle is relocated while preserving its internal layout, use:

```bash
python tools/imu_calibration_provenance.py verify \
  session.manifest.json \
  --base-dir <RESTORED_EVIDENCE_ROOT> \
  --profile promotion
```

`--skip-file-hashes` exists only for structural inspection when the source evidence is unavailable. It should **not** be used to approve a promotion.

## Failure examples

The gate rejects or blocks promotion when, for example:

```text
serial differs across captures
SDK / device / ISP / FPGA revision differs
camera mode differs
capture/report file changed after manifest creation
known analysis role carries the wrong report schema
required six-position or gyro turn is missing
range / ODR / filter configuration is unknown/TBD
manifest is synthetic but promotion was requested
```

## Relationship to final calibration artifacts

The manifest is evidence provenance, not the final numerical calibration artifact.

```text
session manifest
    ↓ verifies compatible immutable evidence
reviewed analysis values
    ↓
bividi.calibration.imu.v1
    ↓
export_kalibr_imu.py
    ↓
Kalibr imu.yaml
```

The final calibration artifact should retain the manifest/session identity and source hash in its provenance so the numerical values remain traceable to the exact evidence bundle.

## Current limitation

The Nori recorder currently records camera/device provenance but not a verified ICM-42688 register snapshot. Therefore the gate cannot independently detect an operator who incorrectly declares an IMU range/filter/ODR. This is an explicit remaining observability gap, not something the manifest hides.

A later hardware-register provenance tool should feed this same gate rather than creating a parallel calibration contract.

Related: `imu-stationary-analysis.md`, `imu-allan-noise-lab.md`, `imu-six-position-axis-lab.md`, `imu-gyro-rotation-lab.md`, Issue #47, Issue #46.
