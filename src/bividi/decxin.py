"""DECXIN/Nori transport decoder used by Bividi's platform-independent adapter.

The decoder intentionally owns only device/protocol behavior. It does not know
about Windows, Linux, macOS, UVC, V4L2, or the Nori host SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import struct
from typing import Any


DECXIN_TRANSPORT_WIDTH = 4000
DECXIN_TRANSPORT_HEIGHT = 1200
DECXIN_METADATA_WIDTH = 160
DECXIN_CAMERA_WIDTH = 1920
NORI_GROUP_SIZE = 16
NORI_CODE_CELL = 8
ICM42688_DEVICE_TYPE = 1
UINT32_MODULUS = 1 << 32
UINT32_HALF_RANGE = 1 << 31


class DecxinDecodeError(ValueError):
    """Raised when a DECXIN/Nori capture is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class BgrFrame:
    """Top-down BGR24 frame with a contiguous row stride."""

    width: int
    height: int
    data: bytes
    row_stride: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame dimensions must be positive")
        if self.row_stride < self.width * 3:
            raise ValueError("row_stride is smaller than BGR24 row width")
        if len(self.data) < self.row_stride * self.height:
            raise ValueError("frame data is shorter than declared geometry")

    def view(self, *, x: int, width: int) -> "ImageView":
        if x < 0 or width <= 0 or x + width > self.width:
            raise ValueError("image view is outside the source frame")
        return ImageView(
            data=memoryview(self.data),
            width=width,
            height=self.height,
            row_stride=self.row_stride,
            offset=x * 3,
            bytes_per_pixel=3,
            pixel_format="bgr24",
        )


@dataclass(frozen=True, slots=True)
class ImageView:
    """Zero-copy rectangular view over an interleaved image buffer."""

    data: memoryview
    width: int
    height: int
    row_stride: int
    offset: int = 0
    bytes_per_pixel: int = 3
    pixel_format: str = "bgr24"

    @property
    def row_bytes(self) -> int:
        return self.width * self.bytes_per_pixel

    def row(self, index: int) -> memoryview:
        if index < 0 or index >= self.height:
            raise IndexError(index)
        start = self.offset + index * self.row_stride
        return self.data[start : start + self.row_bytes]

    def sha256(self) -> str:
        digest = sha256()
        for index in range(self.height):
            digest.update(self.row(index))
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class DeviceGroup:
    device_type: int
    group_count: int


@dataclass(frozen=True, slots=True)
class NoriHeader:
    protocol_type: int
    device_groups: tuple[DeviceGroup, ...]
    exposure_start_raw_us: int
    exposure_end_raw_us: int

    @property
    def total_groups(self) -> int:
        return 1 + sum(group.group_count for group in self.device_groups)


@dataclass(frozen=True, slots=True)
class ImuSample:
    raw_time_us: int
    extended_time_us: int
    accel_raw: tuple[int, int, int]
    gyro_raw: tuple[int, int, int]
    accel_mg: tuple[float, float, float]
    gyro_dps: tuple[float, float, float]
    valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_time_us": self.raw_time_us,
            "extended_time_us": self.extended_time_us,
            "accel_raw": list(self.accel_raw),
            "gyro_raw": list(self.gyro_raw),
            "accel_mg": list(self.accel_mg),
            "gyro_dps": list(self.gyro_dps),
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class DecxinObservation:
    """Normalized result of one DECXIN transport frame.

    ``camera_a``/``camera_b`` are intentionally not called left/right until the
    physical ordering is verified for the actual device.
    """

    camera_a: ImageView
    camera_b: ImageView
    metadata: ImageView
    protocol_type: int
    device_groups: tuple[DeviceGroup, ...]
    exposure_start_raw_us: int
    exposure_end_raw_us: int
    exposure_start_us: int
    exposure_end_us: int
    imu_samples: tuple[ImuSample, ...]
    encoded_payload_sha256: str

    @property
    def exposure_duration_us(self) -> int:
        return self.exposure_end_us - self.exposure_start_us

    def summary(self) -> dict[str, Any]:
        return {
            "format": "decxin-nori-bgr24",
            "protocol_type": self.protocol_type,
            "device_groups": [
                {"device_type": group.device_type, "group_count": group.group_count}
                for group in self.device_groups
            ],
            "camera_a": {
                "width": self.camera_a.width,
                "height": self.camera_a.height,
                "pixel_format": self.camera_a.pixel_format,
                "sha256": self.camera_a.sha256(),
            },
            "camera_b": {
                "width": self.camera_b.width,
                "height": self.camera_b.height,
                "pixel_format": self.camera_b.pixel_format,
                "sha256": self.camera_b.sha256(),
            },
            "metadata": {
                "width": self.metadata.width,
                "height": self.metadata.height,
                "sha256": self.metadata.sha256(),
            },
            "timing": {
                "exposure_start_raw_us": self.exposure_start_raw_us,
                "exposure_end_raw_us": self.exposure_end_raw_us,
                "exposure_start_us": self.exposure_start_us,
                "exposure_end_us": self.exposure_end_us,
                "exposure_duration_us": self.exposure_duration_us,
            },
            "imu": {
                "sample_count": len(self.imu_samples),
                "first_raw_time_us": self.imu_samples[0].raw_time_us if self.imu_samples else None,
                "last_raw_time_us": self.imu_samples[-1].raw_time_us if self.imu_samples else None,
                "valid_samples": sum(sample.valid for sample in self.imu_samples),
            },
            "encoded_payload_sha256": self.encoded_payload_sha256,
        }


class TimestampExtender32:
    """Extend wrapping 32-bit microsecond timestamps into an integer timeline."""

    def __init__(self) -> None:
        self._last_raw: int | None = None
        self._epoch = 0

    def reset(self) -> None:
        self._last_raw = None
        self._epoch = 0

    def extend(self, raw_value: int) -> int:
        if raw_value < 0 or raw_value >= UINT32_MODULUS:
            raise ValueError("timestamp must be an unsigned 32-bit value")
        if self._last_raw is not None:
            # A large backward jump is a forward wrap. Small backward movement
            # remains visible as reordering rather than being silently rewritten.
            if self._last_raw - raw_value > UINT32_HALF_RANGE:
                self._epoch += UINT32_MODULUS
        self._last_raw = raw_value
        return self._epoch + raw_value


def read_bmp24(path: str | Path) -> BgrFrame:
    """Read an uncompressed 24-bit BMP and normalize it to top-down BGR24."""

    raw = Path(path).read_bytes()
    if len(raw) < 54 or raw[:2] != b"BM":
        raise DecxinDecodeError("capture is not a BMP file")

    pixel_offset = struct.unpack_from("<I", raw, 10)[0]
    dib_size = struct.unpack_from("<I", raw, 14)[0]
    if dib_size < 40:
        raise DecxinDecodeError("unsupported BMP DIB header")

    width = struct.unpack_from("<i", raw, 18)[0]
    signed_height = struct.unpack_from("<i", raw, 22)[0]
    planes = struct.unpack_from("<H", raw, 26)[0]
    bits_per_pixel = struct.unpack_from("<H", raw, 28)[0]
    compression = struct.unpack_from("<I", raw, 30)[0]

    if width <= 0 or signed_height == 0:
        raise DecxinDecodeError("invalid BMP dimensions")
    if planes != 1 or bits_per_pixel != 24 or compression != 0:
        raise DecxinDecodeError("only uncompressed BGR24 BMP captures are supported")

    height = abs(signed_height)
    source_stride = ((width * 3 + 3) // 4) * 4
    required = pixel_offset + source_stride * height
    if required > len(raw):
        raise DecxinDecodeError("BMP pixel data is truncated")

    top_down = signed_height < 0
    output_stride = width * 3
    output = bytearray(output_stride * height)
    for y in range(height):
        source_y = y if top_down else height - 1 - y
        src = pixel_offset + source_y * source_stride
        dst = y * output_stride
        output[dst : dst + output_stride] = raw[src : src + output_stride]

    return BgrFrame(width=width, height=height, data=bytes(output), row_stride=output_stride)


def _decode_nori_line(frame: BgrFrame, row_index: int) -> bytes:
    if row_index < 0 or row_index >= frame.height:
        return b""
    row = frame.data[row_index * frame.row_stride : (row_index + 1) * frame.row_stride]
    if len(row) < 4 or not all(value > 220 for value in row[:4]):
        return b""

    channel = 1  # vendor decoder uses the middle BGR byte
    index = 0
    while index < frame.width:
        if row[index * 3 + channel] < 220:
            index += NORI_CODE_CELL // 2
            break
        index += 1
    else:
        return b""

    bits: list[int] = []
    while index + 1 < frame.width:
        value = row[index * 3 + channel] + row[(index + 1) * 3 + channel]
        if value < 100:
            bits.append(0)
        elif value < 440:
            bits.append(1)
        else:
            break
        index += NORI_CODE_CELL

    result = bytearray(len(bits) // 8)
    for byte_index in range(len(result)):
        value = 0
        for bit_index in range(8):
            value |= bits[byte_index * 8 + bit_index] << bit_index
        result[byte_index] = value
    return bytes(result)


def decode_nori_header(group0: bytes) -> NoriHeader:
    if len(group0) != NORI_GROUP_SIZE:
        raise DecxinDecodeError("Nori group 0 must contain exactly 16 bytes")

    if group0[:8] == group0[8:16]:
        # Legacy protocol: duplicated ES/EE data and a fixed 11-sample ICM42688 path.
        start = int.from_bytes(group0[0:4], "big")
        end = int.from_bytes(group0[4:8], "big")
        return NoriHeader(
            protocol_type=0,
            device_groups=(DeviceGroup(ICM42688_DEVICE_TYPE, 11),),
            exposure_start_raw_us=start,
            exposure_end_raw_us=end,
        )

    protocol_type = group0[0] >> 4
    groups = (
        DeviceGroup(((group0[0] & 0x0F) << 4) | ((group0[1] & 0xF0) >> 4), group0[1] & 0x0F),
        DeviceGroup(group0[2], group0[3] >> 4),
        DeviceGroup(((group0[3] & 0x0F) << 4) | ((group0[4] & 0xF0) >> 4), group0[4] & 0x0F),
        DeviceGroup(group0[5], group0[6] >> 4),
        DeviceGroup(((group0[6] & 0x0F) << 4) | ((group0[7] & 0xF0) >> 4), group0[7] & 0x0F),
    )
    start = int.from_bytes(group0[8:12], "big")
    end = int.from_bytes(group0[12:16], "big")
    return NoriHeader(protocol_type, groups, start, end)


def decode_nori_payload(frame: BgrFrame) -> tuple[NoriHeader, bytes]:
    """Decode Nori 8×8 pixel cells into group bytes using vendor semantics."""

    payload = bytearray()
    line_index = 0

    # In a top-down frame the vendor's BMP start row (height - 3 in bottom-up
    # storage) corresponds to logical row 2, then advances downward by 8 pixels.
    while len(payload) < NORI_GROUP_SIZE:
        row_index = 2 + line_index * NORI_CODE_CELL
        line = _decode_nori_line(frame, row_index)
        if not line:
            raise DecxinDecodeError(f"unable to decode Nori header at row {row_index}")
        payload.extend(line)
        line_index += 1
    if len(payload) != NORI_GROUP_SIZE:
        raise DecxinDecodeError("Nori header decoding did not end on a 16-byte boundary")

    header = decode_nori_header(bytes(payload))
    total_size = header.total_groups * NORI_GROUP_SIZE
    if total_size > 4096:
        raise DecxinDecodeError("Nori header declares an unreasonable payload size")

    while len(payload) < total_size:
        row_index = 2 + line_index * NORI_CODE_CELL
        line = _decode_nori_line(frame, row_index)
        if not line:
            raise DecxinDecodeError(f"encoded Nori payload ended early at row {row_index}")
        payload.extend(line)
        line_index += 1

    if len(payload) != total_size:
        raise DecxinDecodeError("Nori payload decoding did not end on the declared group boundary")
    return header, bytes(payload)


def _signed16(value: bytes) -> int:
    return int.from_bytes(value, "big", signed=True)


def decode_icm42688_group(group: bytes, clock: TimestampExtender32 | None = None) -> ImuSample:
    if len(group) != NORI_GROUP_SIZE:
        raise DecxinDecodeError("ICM42688 group must contain exactly 16 bytes")

    raw_time = int.from_bytes(group[0:4], "big")
    accel = tuple(_signed16(group[index : index + 2]) for index in (4, 6, 8))
    gyro = tuple(_signed16(group[index : index + 2]) for index in (10, 12, 14))

    invalid = accel == (-1, -1, -1) or gyro[0] == -32768
    if invalid:
        accel = (0, 0, 0)
        gyro = (0, 0, 0)

    accel_scale_mg = 4000.0 / 32768.0  # vendor demo default: ±4 g
    gyro_scale_dps = 1000.0 / 32768.0  # vendor demo default: ±1000 dps
    extended = clock.extend(raw_time) if clock is not None else raw_time

    return ImuSample(
        raw_time_us=raw_time,
        extended_time_us=extended,
        accel_raw=accel,
        gyro_raw=gyro,
        accel_mg=tuple(value * accel_scale_mg for value in accel),
        gyro_dps=tuple(value * gyro_scale_dps for value in gyro),
        valid=not invalid,
    )


class DecxinDecoder:
    """Stateful DECXIN decoder that keeps timestamp epochs across frames."""

    def __init__(self) -> None:
        self._exposure_clock = TimestampExtender32()
        self._imu_clock = TimestampExtender32()

    def reset_timestamps(self) -> None:
        self._exposure_clock.reset()
        self._imu_clock.reset()

    def decode_bmp(self, path: str | Path) -> DecxinObservation:
        frame = read_bmp24(path)
        return self.decode_bgr(frame)

    def decode_bgr(self, frame: BgrFrame) -> DecxinObservation:
        if frame.width != DECXIN_TRANSPORT_WIDTH or frame.height != DECXIN_TRANSPORT_HEIGHT:
            raise DecxinDecodeError(
                f"unsupported DECXIN transport geometry {frame.width}x{frame.height}; "
                f"expected {DECXIN_TRANSPORT_WIDTH}x{DECXIN_TRANSPORT_HEIGHT}"
            )

        header, payload = decode_nori_payload(frame)
        start_ext = self._exposure_clock.extend(header.exposure_start_raw_us)
        end_ext = self._exposure_clock.extend(header.exposure_end_raw_us)

        imu_samples: list[ImuSample] = []
        group_index = 1
        for device_group in header.device_groups:
            for _ in range(device_group.group_count):
                begin = group_index * NORI_GROUP_SIZE
                group = payload[begin : begin + NORI_GROUP_SIZE]
                if len(group) != NORI_GROUP_SIZE:
                    raise DecxinDecodeError("declared device group exceeds decoded payload")
                if device_group.device_type == ICM42688_DEVICE_TYPE:
                    imu_samples.append(decode_icm42688_group(group, self._imu_clock))
                group_index += 1

        metadata = frame.view(x=0, width=DECXIN_METADATA_WIDTH)
        camera_a = frame.view(x=DECXIN_METADATA_WIDTH, width=DECXIN_CAMERA_WIDTH)
        camera_b = frame.view(
            x=DECXIN_METADATA_WIDTH + DECXIN_CAMERA_WIDTH,
            width=DECXIN_CAMERA_WIDTH,
        )

        return DecxinObservation(
            camera_a=camera_a,
            camera_b=camera_b,
            metadata=metadata,
            protocol_type=header.protocol_type,
            device_groups=header.device_groups,
            exposure_start_raw_us=header.exposure_start_raw_us,
            exposure_end_raw_us=header.exposure_end_raw_us,
            exposure_start_us=start_ext,
            exposure_end_us=end_ext,
            imu_samples=tuple(imu_samples),
            encoded_payload_sha256=sha256(payload).hexdigest(),
        )
