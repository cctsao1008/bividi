from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from bividi.mcap_adapter import (
    McapAdapterError,
    canonicalize_observation,
    read_observations,
    semantic_digest,
    write_observations,
)


def timepoint(ticks=0, *, unit="unknown", domain="unknown", clock_id="", present=False):
    return {
        "ticks": ticks,
        "unit": unit,
        "domain": domain,
        "clock_id": clock_id,
        "present": present,
    }


def raw_time(ticks=0, *, bit_width=0, unit="unknown", clock_id="", present=False):
    return {
        "raw_ticks": ticks,
        "bit_width": bit_width,
        "unit": unit,
        "clock_id": clock_id,
        "present": present,
    }


def exposure(es, ee):
    return {
        "start": timepoint(es, unit="microseconds", domain="device", clock_id="recorded.decXIN.camera", present=True),
        "end": timepoint(ee, unit="microseconds", domain="device", clock_id="recorded.decXIN.camera", present=True),
        "raw_start": raw_time(es & 0xFFFFFFFF, bit_width=32, unit="microseconds", clock_id="recorded.decXIN.camera", present=True),
        "raw_end": raw_time(ee & 0xFFFFFFFF, bit_width=32, unit="microseconds", clock_id="recorded.decXIN.camera", present=True),
    }


def camera(stream_id, data, width, height, pixel_format, es, ee):
    bpp = 1 if pixel_format == "gray8" else 3
    return {
        "stream_id": stream_id,
        "image": {
            "width": width,
            "height": height,
            "row_stride": width * bpp,
            "bytes_per_pixel": bpp,
            "pixel_format": pixel_format,
            "data": data,
        },
        "frame_time": timepoint(),
        "exposure": exposure(es, ee),
        "validity": "valid",
    }


def imu_sample(ticks, raw_ticks, accel, gyro, *, valid=True):
    return {
        "sensor_id": "imu0",
        "sample_time": timepoint(ticks, unit="microseconds", domain="device", clock_id="recorded.decXIN.imu", present=True),
        "raw_time": raw_time(raw_ticks, bit_width=32, unit="microseconds", clock_id="recorded.decXIN.imu", present=True),
        "accel_raw_counts": list(accel),
        "gyro_raw_counts": list(gyro),
        "raw_valid": valid,
        "accel_m_s2": [0.0, 0.0, 0.0],
        "gyro_rad_s": [0.0, 0.0, 0.0],
        "si_valid": False,
        "validity": "valid" if valid else "invalid",
    }


def observation(sequence, host_ns, *, cameras=None, imu=None, continuity="continuous"):
    cameras = list(cameras or [])
    imu = list(imu or [])
    return {
        "contract_version": 1,
        "source_id": "replay:nori:SYN-001",
        "evidence": "synthetic",
        "source_state": "available",
        "validity": "valid" if cameras or any(item["raw_valid"] for item in imu) else "degraded",
        "sequence": sequence,
        "sequence_present": True,
        "continuity_epoch": 0,
        "continuity": continuity,
        "timing": {
            "host_receive": timepoint(host_ns, unit="nanoseconds", domain="host_monotonic", clock_id="recorded.host_receive_monotonic", present=True),
            "replay_schedule": timepoint(),
        },
        "calibration": {"stereo": "", "imu": "", "camera_imu": ""},
        "configuration_revision": "fixture-config",
        "cameras": cameras,
        "imu": imu,
        "stereo_pairs": [{"pair_id": "stereo0", "synchronization": "unknown"}] if cameras else [],
    }


def fixture_observations():
    mono_a = bytes(range(10, 18))
    mono_b = bytes(range(30, 38))
    bgr = bytes(range(60, 60 + 4 * 2 * 3))
    return [
        observation(
            10,
            1_000_000_000,
            continuity="reinitialized",
            cameras=[
                camera("camera_a", mono_a, 4, 2, "gray8", 1000, 1100),
                camera("camera_b", mono_b, 4, 2, "gray8", 1000, 1100),
            ],
            imu=[imu_sample(1050, 1050, (1, 2, 3), (4, 5, 6))],
        ),
        observation(
            11,
            1_001_000_000,
            imu=[imu_sample(2050, 2050, (7, 8, 9), (10, 11, 12))],
        ),
        observation(
            12,
            1_002_000_000,
            cameras=[camera("camera_a", bgr, 4, 2, "bgr24", 3000, 3100)],
            imu=[imu_sample(3050, 3050, (13, 14, 15), (16, 17, 18), valid=False)],
        ),
    ]


class McapAdapterValidationTests(unittest.TestCase):
    def test_canonicalize_rejects_non_tight_image_stride(self):
        sample = fixture_observations()[0]
        sample["cameras"][0]["image"]["row_stride"] = 8
        with self.assertRaisesRegex(McapAdapterError, "tightly packed"):
            canonicalize_observation(sample)

    def test_semantic_digest_covers_producer_timestamps_and_pixels(self):
        sample = fixture_observations()[0]
        digest = semantic_digest(sample)
        changed = fixture_observations()[0]
        changed["timing"]["host_receive"]["ticks"] += 1
        self.assertNotEqual(digest, semantic_digest(changed))
        changed = fixture_observations()[0]
        payload = bytearray(changed["cameras"][0]["image"]["data"])
        payload[0] ^= 0xFF
        changed["cameras"][0]["image"]["data"] = bytes(payload)
        self.assertNotEqual(digest, semantic_digest(changed))


@unittest.skipUnless(importlib.util.find_spec("mcap") is not None, "optional mcap dependency is not installed")
class McapAdapterRoundTripTests(unittest.TestCase):
    def test_stereo_imu_round_trip_is_semantically_exact(self):
        source = fixture_observations()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.mcap"
            report = write_observations(path, source)
            restored = read_observations(path)

        self.assertEqual(report["schema"], "bividi.mcap.export.v1")
        self.assertEqual(report["observations"], 3)
        self.assertEqual(report["camera_channels"], 2)
        self.assertEqual(len(restored), len(source))
        self.assertEqual([semantic_digest(item) for item in restored], [semantic_digest(item) for item in source])
        self.assertEqual(restored[0]["cameras"][0]["image"]["data"], source[0]["cameras"][0]["image"]["data"])
        self.assertEqual(restored[0]["timing"]["host_receive"], source[0]["timing"]["host_receive"])
        self.assertEqual(restored[0]["cameras"][0]["exposure"], source[0]["cameras"][0]["exposure"])
        self.assertEqual(restored[1]["imu"][0]["raw_time"], source[1]["imu"][0]["raw_time"])
        self.assertEqual(restored[0]["stereo_pairs"][0]["synchronization"], "unknown")

    def test_writer_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.mcap"
            write_observations(path, fixture_observations())
            with self.assertRaisesRegex(McapAdapterError, "refusing to overwrite"):
                write_observations(path, fixture_observations())


if __name__ == "__main__":
    unittest.main()
