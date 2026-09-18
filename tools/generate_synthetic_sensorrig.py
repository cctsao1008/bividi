#!/usr/bin/env python3
"""Generate deterministic hardware-independent stereo-inertial SensorRig fixtures.

The generated directory intentionally matches the existing Bividi Nori-session
replay adapter surface (capture.json / frames.csv / imu.csv / camera_a / camera_b)
while carrying independent synthetic ground-truth metadata. It is test evidence,
not physical AR0234 evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "bividi.synthetic_sensor_rig.v1"
CAPTURE_SCHEMA = "bividi.nori.camera_imu_dynamic_trace.v1"
G = 9.80665


@dataclass(frozen=True)
class RigConfig:
    width: int = 96
    height: int = 64
    fx_px: float = 80.0
    fy_px: float = 80.0
    cx_px: float = 47.5
    cy_px: float = 31.5
    baseline_m: float = 0.10
    plane_depth_m: float = 2.0
    fps: float = 30.0
    imu_hz: float = 200.0
    exposure_us: int = 5000
    accel_counts_per_g: float = 16384.0
    gyro_counts_per_rad_s: float = 7500.0
    seed: int = 0xB1D1D1


def canonical_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        h.update(len(rel).to_bytes(4, "little"))
        h.update(rel)
        h.update(len(data).to_bytes(8, "little"))
        h.update(data)
    return h.hexdigest()


def _hash_pixel(seed: int, x: int, y: int) -> int:
    # Stateless integer mix: deterministic across Python versions/platforms.
    v = (seed ^ ((x + 0x9E37) * 0x45D9F3B) ^ ((y + 0x7F4A) * 0x27D4EB2D)) & 0xFFFFFFFF
    v ^= v >> 16
    v = (v * 0x7FEB352D) & 0xFFFFFFFF
    v ^= v >> 15
    v = (v * 0x846CA68B) & 0xFFFFFFFF
    v ^= v >> 16
    return 24 + (v % 208)


def render_textured_plane(
    cfg: RigConfig,
    *,
    camera_motion_px: int,
    stereo_offset_px: int,
) -> bytes:
    pixels = bytearray(cfg.width * cfg.height)
    for y in range(cfg.height):
        row = y * cfg.width
        for x in range(cfg.width):
            world_x = x + camera_motion_px + stereo_offset_px
            # Add large deterministic structures over the hash texture so
            # classical stereo has both fine and coarse support.
            base = _hash_pixel(cfg.seed, world_x, y)
            checker = 36 if (((world_x // 8) + (y // 8)) & 1) else -36
            pixels[row + x] = max(0, min(255, base + checker))
    return bytes(pixels)


def write_pgm(path: Path, width: int, height: int, pixels: bytes) -> None:
    if len(pixels) != width * height:
        raise ValueError("PGM payload size mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"P5\n{width} {height}\n255\n".encode("ascii") + pixels)


def imu_to_camera_rotation() -> list[list[float]]:
    # IMU/world FLU: +X forward, +Y left, +Z up.
    # OpenCV camera: +X right, +Y down, +Z forward.
    # v_cam = [-v_imu_y, -v_imu_z, v_imu_x].
    return [
        [0.0, -1.0, 0.0],
        [0.0, 0.0, -1.0],
        [1.0, 0.0, 0.0],
    ]


def expected_disparity_px(cfg: RigConfig) -> float:
    return cfg.fx_px * cfg.baseline_m / cfg.plane_depth_m


def frame_period_us(cfg: RigConfig) -> int:
    return int(round(1_000_000.0 / cfg.fps))


def imu_period_us(cfg: RigConfig) -> int:
    return int(round(1_000_000.0 / cfg.imu_hz))


def _camera_motion_x_m(scenario: str, t_s: float) -> tuple[float, float, float]:
    if scenario == "static-plane":
        return 0.0, 0.0, 0.0
    # Smooth lateral motion in camera +X (right), 2 cm amplitude, 0.5 Hz.
    amp = 0.02
    omega = 2.0 * math.pi * 0.5
    x = amp * math.sin(omega * t_s)
    v = amp * omega * math.cos(omega * t_s)
    a = -amp * omega * omega * math.sin(omega * t_s)
    return x, v, a


def _raw_accel(cfg: RigConfig, camera_x_accel_m_s2: float) -> tuple[int, int, int]:
    # Camera +X(right) == IMU -Y(left). At fixed orientation, specific force
    # at rest is +g on IMU +Z. Add the trajectory acceleration in IMU -Y.
    specific_force = (0.0, -camera_x_accel_m_s2, G)
    counts_per_m_s2 = cfg.accel_counts_per_g / G
    return tuple(int(round(v * counts_per_m_s2)) for v in specific_force)


def _raw_gyro(cfg: RigConfig) -> tuple[int, int, int]:
    # First moving fixture is pure translation. Angular velocity is exactly zero.
    return (0, 0, 0)


def _write_capture_json(root: Path, cfg: RigConfig, scenario: str) -> None:
    capture = {
        "schema": CAPTURE_SCHEMA,
        "provenance": {
            "kind": "synthetic",
            "generator_schema": SCHEMA,
            "generator": "tools/generate_synthetic_sensorrig.py",
            "seed": cfg.seed,
        },
        "device": {
            "product": "Bividi Synthetic SensorRig",
            "serial": f"SYN-{scenario.upper()}",
            "sdk_version": "synthetic-none",
            "device_type": "synthetic-stereo-inertial",
            "isp_version": "synthetic-none",
            "fpga_version": "synthetic-none",
        },
        "mode": {
            "index": 0,
            "nominal_fps": cfg.fps,
        },
        "run": {
            "frame_stride": 1,
        },
    }
    (root / "capture.json").write_text(json.dumps(capture, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _trajectory_entry(cfg: RigConfig, scenario: str, frame_index: int, t_s: float) -> dict:
    x, v, a = _camera_motion_x_m(scenario, t_s)
    return {
        "frame_index": frame_index,
        "t_s": round(t_s, 9),
        "camera_a_position_m": [round(x, 12), 0.0, 0.0],
        "camera_a_velocity_m_s": [round(v, 12), 0.0, 0.0],
        "camera_a_acceleration_m_s2": [round(a, 12), 0.0, 0.0],
        "orientation_camera_from_world": [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
    }


def generate(root: Path, scenario: str, *, frames: int | None = None) -> dict:
    if scenario not in {"static-plane", "moving-rig"}:
        raise ValueError(f"unsupported scenario: {scenario}")

    cfg = RigConfig()
    root = Path(root)
    if root.exists():
        if any(root.iterdir()):
            raise FileExistsError(f"output directory is not empty: {root}")
    else:
        root.mkdir(parents=True)
    (root / "camera_a").mkdir()
    (root / "camera_b").mkdir()

    frame_count = frames if frames is not None else (6 if scenario == "static-plane" else 30)
    if frame_count < 2:
        raise ValueError("frames must be >= 2")

    disparity_f = expected_disparity_px(cfg)
    disparity = int(round(disparity_f))
    if abs(disparity_f - disparity) > 1e-12 or disparity <= 0:
        raise ValueError("fixture requires positive integer disparity")

    start_us = 1_000_000
    host_start_ns = 5_000_000_000
    frame_dt_us = frame_period_us(cfg)
    imu_dt_us = imu_period_us(cfg)

    frame_rows: list[list[object]] = []
    imu_rows: list[list[object]] = []
    trajectory: list[dict] = []

    for i in range(frame_count):
        t_s = i / cfg.fps
        x_m, _, _ = _camera_motion_x_m(scenario, t_s)
        motion_px = int(round(cfg.fx_px * x_m / cfg.plane_depth_m))

        a_pixels = render_textured_plane(cfg, camera_motion_px=motion_px, stereo_offset_px=0)
        b_pixels = render_textured_plane(cfg, camera_motion_px=motion_px, stereo_offset_px=disparity)
        name = f"{i:010d}.pgm"
        write_pgm(root / "camera_a" / name, cfg.width, cfg.height, a_pixels)
        write_pgm(root / "camera_b" / name, cfg.width, cfg.height, b_pixels)

        es_ext = start_us + i * frame_dt_us
        ee_ext = es_ext + cfg.exposure_us
        es_raw = es_ext & 0xFFFFFFFF
        ee_raw = ee_ext & 0xFFFFFFFF
        host_ns = host_start_ns + i * int(round(1_000_000_000.0 / cfg.fps))
        sequence = 1000 + i

        frame_rows.append([
            i, sequence, host_ns,
            "synthetic", 0, 0, 0,
            es_raw, ee_raw, es_ext, ee_ext,
            f"camera_a/{name}", f"camera_b/{name}",
        ])
        trajectory.append(_trajectory_entry(cfg, scenario, i, t_s))

        # Generate device-domain IMU samples assigned to this video frame.
        next_es = start_us + (i + 1) * frame_dt_us
        sample_t = es_ext
        sample_index = 0
        while sample_t < next_es:
            sample_t_s = (sample_t - start_us) / 1_000_000.0
            _, _, accel_x = _camera_motion_x_m(scenario, sample_t_s)
            ax, ay, az = _raw_accel(cfg, accel_x)
            gx, gy, gz = _raw_gyro(cfg)
            imu_rows.append([
                i, sequence, host_ns,
                es_raw, ee_raw, es_ext, ee_ext,
                sample_index, "true",
                sample_t & 0xFFFFFFFF, sample_t,
                ax, ay, az, gx, gy, gz,
            ])
            sample_index += 1
            sample_t += imu_dt_us

    with (root / "frames.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "frame_index", "frame_sequence", "host_receive_monotonic_ns",
            "sdk_timestamp_encoding", "sdk_seconds", "sdk_microseconds", "sdk_filetime_100ns",
            "exposure_start_raw_us", "exposure_end_raw_us",
            "exposure_start_extended_us", "exposure_end_extended_us",
            "camera_a_path", "camera_b_path",
        ])
        w.writerows(frame_rows)

    with (root / "imu.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "frame_index", "frame_sequence", "host_receive_monotonic_ns",
            "exposure_start_raw_us", "exposure_end_raw_us",
            "exposure_start_extended_us", "exposure_end_extended_us",
            "sample_index", "sample_valid", "imu_raw_time_us", "imu_extended_time_us",
            "accel_raw_x", "accel_raw_y", "accel_raw_z",
            "gyro_raw_x", "gyro_raw_y", "gyro_raw_z",
        ])
        w.writerows(imu_rows)

    _write_capture_json(root, cfg, scenario)

    ground_truth = {
        "schema": SCHEMA,
        "provenance": {
            "kind": "synthetic",
            "seed": cfg.seed,
            "physical_hardware_evidence": False,
        },
        "scenario": scenario,
        "session_adapter_schema": CAPTURE_SCHEMA,
        "frames": frame_count,
        "rig": {
            "camera_a": {
                "frame": "camera_a_optical",
                "projection": "pinhole",
                "resolution": [cfg.width, cfg.height],
                "K": [
                    [cfg.fx_px, 0.0, cfg.cx_px],
                    [0.0, cfg.fy_px, cfg.cy_px],
                    [0.0, 0.0, 1.0],
                ],
                "D": [0.0, 0.0, 0.0, 0.0, 0.0],
            },
            "camera_b": {
                "frame": "camera_b_optical",
                "projection": "pinhole",
                "resolution": [cfg.width, cfg.height],
                "K": [
                    [cfg.fx_px, 0.0, cfg.cx_px],
                    [0.0, cfg.fy_px, cfg.cy_px],
                    [0.0, 0.0, 1.0],
                ],
                "D": [0.0, 0.0, 0.0, 0.0, 0.0],
            },
            "stereo": {
                "transform_definition": "camera_a_coordinates_to_camera_b_coordinates",
                "R_camera_b_from_camera_a": [
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
                "T_camera_b_from_camera_a_m": [-cfg.baseline_m, 0.0, 0.0],
                "baseline_m": cfg.baseline_m,
            },
            "imu": {
                "frame": "imu0",
                "axes": "right-handed FLU: +X forward, +Y left, +Z up",
                "accel_counts_per_g": cfg.accel_counts_per_g,
                "gyro_counts_per_rad_s": cfg.gyro_counts_per_rad_s,
                "sample_rate_hz": cfg.imu_hz,
            },
            "camera_imu": {
                "transform_definition": "imu0_coordinates_to_camera_a_optical_coordinates",
                "R_camera_a_from_imu": imu_to_camera_rotation(),
                "T_camera_a_from_imu_m": [0.0, 0.0, 0.0],
                "time_offset_definition": "t_imu = t_camera_reference + offset_s",
                "time_offset_s": 0.0,
            },
        },
        "scene": {
            "kind": "fronto_parallel_textured_plane",
            "plane_depth_m": cfg.plane_depth_m,
            "expected_disparity_px": disparity_f,
            "disparity_formula": "fx_px * baseline_m / plane_depth_m",
            "valid_correspondence_region": {
                "camera_a_x_min": disparity,
                "camera_a_x_max_inclusive": cfg.width - 1,
            },
        },
        "timing": {
            "device_clock_id": "synthetic-device-us",
            "camera_fps": cfg.fps,
            "exposure_us": cfg.exposure_us,
            "imu_hz": cfg.imu_hz,
            "raw_timestamp_bit_width": 32,
            "host_clock_relation": "arbitrary independent monotonic provenance; not a sensor-time calibration",
        },
        "trajectory": trajectory,
    }

    # Bind the native replay evidence files and media payloads without creating a
    # self-referential hash over ground_truth.json itself.
    artifact_hashes = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "ground_truth.json"):
        artifact_hashes[path.relative_to(root).as_posix()] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    ground_truth["artifact_hashes"] = artifact_hashes
    (root / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return ground_truth


def _read_pgm_pixels(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    # Generated files have exactly three header lines and no comments.
    magic, dims, maxval, payload = data.split(b"\n", 3)
    if magic != b"P5" or maxval != b"255":
        raise AssertionError("unexpected PGM encoding")
    width, height = (int(v) for v in dims.split())
    if len(payload) != width * height:
        raise AssertionError("PGM payload length mismatch")
    return width, height, payload


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="bividi-synth-a-") as a_tmp, \
         tempfile.TemporaryDirectory(prefix="bividi-synth-b-") as b_tmp:
        a = Path(a_tmp) / "static"
        b = Path(b_tmp) / "static"
        ga = generate(a, "static-plane", frames=4)
        gb = generate(b, "static-plane", frames=4)
        assert canonical_json(ga) == canonical_json(gb)
        assert tree_digest(a) == tree_digest(b)
        assert abs(ga["scene"]["expected_disparity_px"] - 4.0) < 1e-12

        w, h, pa = _read_pgm_pixels(a / "camera_a" / "0000000000.pgm")
        wb, hb, pb = _read_pgm_pixels(a / "camera_b" / "0000000000.pgm")
        assert (w, h) == (96, 64) == (wb, hb)
        d = int(ga["scene"]["expected_disparity_px"])
        for y in (3, 17, 42):
            for x in (0, 11, 35, 70):
                if x + d < w:
                    assert pb[y * w + x] == pa[y * w + x + d]

        capture = json.loads((a / "capture.json").read_text(encoding="utf-8"))
        assert capture["provenance"]["kind"] == "synthetic"

    with tempfile.TemporaryDirectory(prefix="bividi-synth-moving-") as tmp:
        root = Path(tmp) / "moving"
        gt = generate(root, "moving-rig", frames=12)
        assert gt["provenance"]["kind"] == "synthetic"
        first = (root / "camera_a" / "0000000000.pgm").read_bytes()
        later = (root / "camera_a" / "0000000010.pgm").read_bytes()
        assert first != later

        with (root / "imu.csv").open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        ay = {int(r["accel_raw_y"]) for r in rows}
        az = {int(r["accel_raw_z"]) for r in rows}
        assert len(ay) > 1
        assert az == {16384}
        assert all(int(r["gyro_raw_x"]) == 0 for r in rows)
        assert all(int(r["gyro_raw_y"]) == 0 for r in rows)
        assert all(int(r["gyro_raw_z"]) == 0 for r in rows)

    print("synthetic SensorRig generator self-test: PASS")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", nargs="?", type=Path)
    p.add_argument("--scenario", choices=["static-plane", "moving-rig"], default="static-plane")
    p.add_argument("--frames", type=int)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--print-digest", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("output directory is required unless --self-test is used")
    gt = generate(args.output, args.scenario, frames=args.frames)
    print(f"generated {args.scenario}: {args.output}")
    print(f"schema: {gt['schema']}")
    print(f"frames: {gt['frames']}")
    print(f"expected disparity: {gt['scene']['expected_disparity_px']:.6f} px")
    if args.print_digest:
        print(f"tree sha256: {tree_digest(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
