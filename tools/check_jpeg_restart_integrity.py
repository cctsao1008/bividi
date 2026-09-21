#!/usr/bin/env python3
"""Check JPEG restart-marker integrity for DECXIN/Nori MJPEG packets.

This is intentionally decoder-independent: it inspects the compressed JPEG
packet structure before FFmpeg/OpenCV/libjpeg concealment can alter pixels.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


@dataclass
class RestartError:
    index: int
    offset: int
    expected: int
    actual: int


@dataclass
class JpegIntegrity:
    path: str
    bytes: int
    soi: bool = False
    eoi: bool = False
    sos: bool = False
    dri_interval: int | None = None
    width: int | None = None
    height: int | None = None
    mcu_width: int | None = None
    mcu_height: int | None = None
    expected_restart_count: int | None = None
    restart_count: int = 0
    restart_errors: list[RestartError] = field(default_factory=list)
    unexpected_markers: list[dict[str, int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.restart_errors and not self.unexpected_markers


def _read_segment_length(data: bytes, pos: int) -> tuple[int, int]:
    if pos + 2 > len(data):
        raise ValueError("truncated segment length")
    length = int.from_bytes(data[pos : pos + 2], "big")
    if length < 2:
        raise ValueError("invalid JPEG segment length")
    end = pos + length
    if end > len(data):
        raise ValueError("JPEG segment extends beyond packet")
    return length, end


def inspect_jpeg_bytes(data: bytes, path: str = "<memory>") -> JpegIntegrity:
    result = JpegIntegrity(path=path, bytes=len(data))
    if len(data) < 4:
        result.errors.append("packet too short")
        return result

    result.soi = data[:2] == b"\xff\xd8"
    result.eoi = data[-2:] == b"\xff\xd9"
    if not result.soi:
        result.errors.append("missing SOI")
        return result
    if not result.eoi:
        result.errors.append("missing terminal EOI")

    pos = 2
    entropy_start: int | None = None
    max_h = 0
    max_v = 0

    try:
        while pos < len(data) - 1:
            if data[pos] != 0xFF:
                result.errors.append(f"expected marker prefix before SOS at offset {pos}")
                return result
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                break

            marker = data[pos]
            pos += 1

            if marker == 0xD8:
                continue
            if marker == 0xD9:
                break
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue

            length, end = _read_segment_length(data, pos)
            payload = data[pos + 2 : end]

            if marker == 0xDD:
                if len(payload) != 2:
                    result.errors.append("invalid DRI payload length")
                else:
                    result.dri_interval = int.from_bytes(payload, "big")

            if marker in SOF_MARKERS:
                if len(payload) < 6:
                    result.errors.append("truncated SOF payload")
                else:
                    result.height = int.from_bytes(payload[1:3], "big")
                    result.width = int.from_bytes(payload[3:5], "big")
                    components = payload[5]
                    expected = 6 + 3 * components
                    if len(payload) < expected:
                        result.errors.append("truncated SOF component table")
                    else:
                        for i in range(components):
                            sampling = payload[7 + 3 * i]
                            max_h = max(max_h, sampling >> 4)
                            max_v = max(max_v, sampling & 0x0F)

            if marker == 0xDA:
                result.sos = True
                entropy_start = end
                break

            pos = end
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    if not result.sos or entropy_start is None:
        result.errors.append("SOS not found")
        return result

    if result.width and result.height and max_h and max_v:
        result.mcu_width = 8 * max_h
        result.mcu_height = 8 * max_v
        if result.dri_interval and result.dri_interval > 0:
            mcu_cols = math.ceil(result.width / result.mcu_width)
            mcu_rows = math.ceil(result.height / result.mcu_height)
            total_mcus = mcu_cols * mcu_rows
            result.expected_restart_count = (total_mcus - 1) // result.dri_interval

    restarts: list[tuple[int, int]] = []
    pos = entropy_start
    while pos < len(data) - 1:
        if data[pos] != 0xFF:
            pos += 1
            continue

        start = pos
        pos += 1
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break

        marker = data[pos]
        pos += 1
        if marker == 0x00:
            continue
        if 0xD0 <= marker <= 0xD7:
            restarts.append((start, marker - 0xD0))
            continue
        if marker == 0xD9:
            break

        result.unexpected_markers.append({"offset": start, "marker": marker})

    result.restart_count = len(restarts)

    expected_rst = 0
    for index, (offset, actual) in enumerate(restarts):
        if actual != expected_rst:
            result.restart_errors.append(
                RestartError(
                    index=index,
                    offset=offset,
                    expected=expected_rst,
                    actual=actual,
                )
            )
            expected_rst = (actual + 1) & 7
        else:
            expected_rst = (expected_rst + 1) & 7

    if (
        result.expected_restart_count is not None
        and result.restart_count != result.expected_restart_count
    ):
        result.errors.append(
            f"restart count {result.restart_count} != expected {result.expected_restart_count}"
        )

    return result


def inspect_path(path: Path) -> JpegIntegrity:
    return inspect_jpeg_bytes(path.read_bytes(), str(path))


def iter_inputs(source: Path, pattern: str) -> Iterable[Path]:
    if source.is_file():
        yield source
        return
    if not source.is_dir():
        raise FileNotFoundError(source)
    yield from sorted(p for p in source.glob(pattern) if p.is_file())


def synthetic_jpeg(restarts: list[int]) -> bytes:
    # Structurally sufficient baseline JPEG for marker testing:
    # 32x8 grayscale => four 8x8 MCUs, DRI=1 => three RST markers expected.
    sof = bytes.fromhex("ffc0000b080008002001011100")
    dri = bytes.fromhex("ffdd00040001")
    sos = bytes.fromhex("ffda0008010100003f00")
    entropy = bytearray(b"\x11\x22")
    for rst in restarts:
        entropy.extend((0xFF, 0xD0 + rst))
        entropy.extend(b"\x33\x44")
    return b"\xff\xd8" + sof + dri + sos + bytes(entropy) + b"\xff\xd9"


def self_test() -> None:
    good = inspect_jpeg_bytes(synthetic_jpeg([0, 1, 2]), "good")
    if not good.ok or good.restart_count != 3 or good.expected_restart_count != 3:
        raise SystemExit(f"self-test good case failed: {asdict(good)}")

    bad = inspect_jpeg_bytes(synthetic_jpeg([0, 2]), "bad")
    if bad.ok:
        raise SystemExit("self-test bad case unexpectedly passed")
    if not bad.restart_errors or bad.restart_errors[0].expected != 1 or bad.restart_errors[0].actual != 2:
        raise SystemExit(f"self-test did not detect skipped RST1: {asdict(bad)}")
    print("JPEG restart integrity self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--glob", default="*.jpg")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--show-clean", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.source is None:
        parser.error("source is required unless --self-test is used")

    inspected = 0
    anomalies = 0
    dri_values: set[int] = set()
    restart_counts: set[int] = set()

    for path in iter_inputs(args.source, args.glob):
        result = inspect_path(path)
        inspected += 1
        if result.dri_interval is not None:
            dri_values.add(result.dri_interval)
        restart_counts.add(result.restart_count)
        if not result.ok:
            anomalies += 1

        if args.json and (args.show_clean or not result.ok):
            print(json.dumps(asdict(result), sort_keys=True))
        elif not args.json and (args.show_clean or not result.ok):
            print(
                f"{'PASS' if result.ok else 'FAIL'} {result.path} "
                f"bytes={result.bytes} DRI={result.dri_interval} "
                f"RST={result.restart_count}/{result.expected_restart_count}"
            )
            for error in result.restart_errors:
                print(
                    "  restart sequence error: "
                    f"index={error.index} offset={error.offset} "
                    f"expected=RST{error.expected} actual=RST{error.actual}"
                )
            for marker in result.unexpected_markers:
                print(
                    f"  unexpected marker: offset={marker['offset']} "
                    f"marker=0x{marker['marker']:02x}"
                )
            for error in result.errors:
                print(f"  {error}")

    summary = {
        "files": inspected,
        "clean": inspected - anomalies,
        "anomalies": anomalies,
        "dri_values": sorted(dri_values),
        "restart_counts": sorted(restart_counts),
    }
    if args.json:
        print(json.dumps({"summary": summary}, sort_keys=True))
    else:
        print(
            "summary: "
            f"files={summary['files']} clean={summary['clean']} "
            f"anomalies={summary['anomalies']} "
            f"DRI={summary['dri_values']} RST_counts={summary['restart_counts']}"
        )

    if inspected == 0:
        return 2
    return 1 if anomalies else 0


if __name__ == "__main__":
    raise SystemExit(main())
