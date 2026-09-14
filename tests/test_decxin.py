import hashlib
import json
from pathlib import Path
import unittest

from bividi.decxin import (
    DecxinDecodeError,
    TimestampExtender32,
    decode_icm42688_group,
    decode_nori_header,
)


FIXTURE = Path(__file__).parent / "fixtures" / "decxin_ar0234_sample_vector.json"


class DecxinVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vector = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.groups = [bytes.fromhex(value) for value in cls.vector["groups_hex"]]

    def test_vendor_sample_header_vector(self) -> None:
        expected = self.vector["expected"]
        header = decode_nori_header(self.groups[0])
        self.assertEqual(header.protocol_type, expected["protocol_type"])
        self.assertEqual(header.exposure_start_raw_us, expected["exposure_start_raw_us"])
        self.assertEqual(header.exposure_end_raw_us, expected["exposure_end_raw_us"])
        self.assertEqual(
            [(item.device_type, item.group_count) for item in header.device_groups],
            [(item["device_type"], item["group_count"]) for item in expected["device_groups"]],
        )
        self.assertEqual(header.total_groups, len(self.groups))

    def test_vendor_sample_icm42688_vectors(self) -> None:
        expected = self.vector["expected"]
        clock = TimestampExtender32()
        samples = [decode_icm42688_group(group, clock) for group in self.groups[1:]]
        self.assertEqual(len(samples), expected["imu_count"])
        self.assertEqual([sample.raw_time_us for sample in samples], expected["imu_raw_times_us"])
        self.assertEqual(samples[0].accel_raw, tuple(expected["first_imu_raw"]["accel"]))
        self.assertEqual(samples[0].gyro_raw, tuple(expected["first_imu_raw"]["gyro"]))
        self.assertEqual(samples[-1].accel_raw, tuple(expected["last_imu_raw"]["accel"]))
        self.assertEqual(samples[-1].gyro_raw, tuple(expected["last_imu_raw"]["gyro"]))
        self.assertTrue(all(sample.valid for sample in samples))

    def test_payload_hash_is_stable(self) -> None:
        payload = b"".join(self.groups)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), self.vector["encoded_payload_sha256"])

    def test_timestamp_rollover_extension(self) -> None:
        clock = TimestampExtender32()
        self.assertEqual(clock.extend(0xFFFFFFF0), 0xFFFFFFF0)
        self.assertEqual(clock.extend(0xFFFFFFFE), 0xFFFFFFFE)
        self.assertEqual(clock.extend(0x00000020), (1 << 32) + 0x20)

    def test_small_backward_timestamp_is_not_hidden_as_rollover(self) -> None:
        clock = TimestampExtender32()
        self.assertEqual(clock.extend(1000), 1000)
        self.assertEqual(clock.extend(900), 900)

    def test_vendor_invalid_imu_sentinel_is_explicit(self) -> None:
        group = (123).to_bytes(4, "big") + b"\xff\xff" * 3 + b"\x00\x01" * 3
        sample = decode_icm42688_group(group)
        self.assertFalse(sample.valid)
        self.assertEqual(sample.accel_raw, (0, 0, 0))
        self.assertEqual(sample.gyro_raw, (0, 0, 0))

    def test_group_size_is_strict(self) -> None:
        with self.assertRaises(DecxinDecodeError):
            decode_nori_header(b"\x00" * 15)


if __name__ == "__main__":
    unittest.main()
