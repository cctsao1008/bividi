"""Verify the external DECXIN vendor BMP against the compact repository vector."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from bividi.decxin import DecxinDecoder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument(
        "--vector",
        type=Path,
        default=Path(__file__).parents[1] / "tests" / "fixtures" / "decxin_ar0234_sample_vector.json",
    )
    args = parser.parse_args()

    vector = json.loads(args.vector.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(args.capture.read_bytes()).hexdigest()
    if source_hash != vector["source_sha256"]:
        raise SystemExit(f"source SHA-256 mismatch: {source_hash}")

    observation = DecxinDecoder().decode_bmp(args.capture)
    summary = observation.summary()
    expected = vector["expected"]

    checks = {
        "encoded payload": summary["encoded_payload_sha256"] == vector["encoded_payload_sha256"],
        "metadata region": summary["metadata"]["sha256"] == vector["regions"]["metadata"]["sha256"],
        "camera A": summary["camera_a"]["sha256"] == vector["regions"]["camera_a"]["sha256"],
        "camera B": summary["camera_b"]["sha256"] == vector["regions"]["camera_b"]["sha256"],
        "exposure start": summary["timing"]["exposure_start_raw_us"] == expected["exposure_start_raw_us"],
        "exposure end": summary["timing"]["exposure_end_raw_us"] == expected["exposure_end_raw_us"],
        "IMU sample count": summary["imu"]["sample_count"] == expected["imu_count"],
    }

    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    if not all(checks.values()):
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
